import os
import time
import random
import math
from collections import deque
import numpy as np

import gymnasium as gym   # works also for old gym API with small tweaks
import pykachu_env
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical
from tqdm import trange, tqdm


# ------------ Config ------------
ENV_ID = 'PykachuVolleyball-v0'  # adjust if your env id is different
ACTION_DIMS = [3, 3, 2]          # MultiDiscrete([3, 3, 2])
DOWNSAMPLED_SHAPE = (160, 120)   # (H, W) after downsampling
FRAME_STACK = 3                  # how many recent frames to stack (channel-wise)
ACTION_REPEAT = 2                # repeat each action this many env steps

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

TOTAL_UPDATES    = 250          # how many PPO updates
ROLLOUT_STEPS    = 2048          # steps per rollout
GAMMA            = 0.995
GAE_LAMBDA       = 0.95
PPO_EPOCHS       = 4
MINIBATCH_SIZE   = 1024
CLIP_EPS         = 0.1
LR_START         = 3e-4
LR_END           = 5e-5
LR_DECAY_K       = 0.5           # unused when linear
VF_COEF          = 0.5
VALUE_CLIP       = 0.2
ENT_COEF_START   = 0.02
ENT_COEF_END     = 0.01
ENT_DECAY_K      = 0.5           # unused when linear
MAX_GRAD_NORM    = 0.5


# ------------ Utils ------------
def set_seed(seed=0):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def downsample_obs(obs_np):
    """
    Downsample (H, W, C) uint8 observation to DOWNSAMPLED_SHAPE while keeping uint8.
    """
    obs_t = torch.from_numpy(obs_np).float().permute(2, 0, 1).unsqueeze(0)  # (1, C, H, W)
    obs_t = F.interpolate(
        obs_t,
        size=DOWNSAMPLED_SHAPE,
        mode="bilinear",
        align_corners=False,
        antialias=True,
    )
    obs_t = obs_t.clamp(0, 255).byte().squeeze(0).permute(1, 2, 0)  # (H, W, C)
    return obs_t.numpy()


def obs_to_tensor(obs_np):
    """
    Convert uint8 (H, W, C) to float tensor on DEVICE in [0,1].
    """
    return torch.from_numpy(obs_np).to(DEVICE).float() / 255.0


def stack_frames(frames_deque):
    """
    Concatenate a deque of frames along the channel axis.
    """
    return np.concatenate(list(frames_deque), axis=-1)


# ------------ Network ------------
class PikachuPPO(nn.Module):
    """
    CNN encoder + 3 categorical policy heads (for MultiDiscrete)
    + value head.
    """
    def __init__(self, action_dims=ACTION_DIMS, input_channels=3 * FRAME_STACK):
        super().__init__()
        self.action_dims = action_dims

        # Input: (B, H, W, C) with H=DOWNSAMPLED_SHAPE[0], W=DOWNSAMPLED_SHAPE[1], C=input_channels
        # We'll internally permute to (B, C, H, W).
        self.conv = nn.Sequential(
            nn.Conv2d(input_channels, 64, kernel_size=8, stride=4),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=4, stride=2),
            nn.ReLU(),
            nn.Conv2d(128, 128, kernel_size=3, stride=1),
            nn.ReLU(),
        )

        # Figure out conv output size by doing a dummy forward
        with torch.no_grad():
            dummy = torch.zeros(1, input_channels, DOWNSAMPLED_SHAPE[0], DOWNSAMPLED_SHAPE[1])
            conv_out = self.conv(dummy)
            conv_out_size = conv_out.view(1, -1).size(1)

        # Shared trunk
        self.shared = nn.Sequential(
            nn.Linear(conv_out_size, 512),
            nn.LayerNorm(512),
            nn.ReLU(),
        )

        # Actor tower
        self.actor_body = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
        )
        self.policy_heads = nn.ModuleList([nn.Linear(256, n) for n in action_dims])

        # Critic tower
        self.critic_body = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 1),
        )

    def forward(self, obs):
        """
        obs: float tensor in [0,1], shape (B, H, W, C)
        """
        # (B, H, W, C) -> (B, C, H, W)
        x = obs.permute(0, 3, 1, 2)
        x = self.conv(x)
        x = x.reshape(x.size(0), -1)
        x = self.shared(x)

        actor_feat = self.actor_body(x)
        logits_list = [head(actor_feat) for head in self.policy_heads]

        value = self.critic_body(x).squeeze(-1)
        return logits_list, value

    def get_action_and_value(self, obs, action=None):
        """
        obs: float tensor in [0,1], shape (B, H, W, C)
        action: optional tensor of shape (B, 3) with ints
        """
        logits_list, value = self.forward(obs)
        dists = [Categorical(logits=logits) for logits in logits_list]

        if action is None:
            # Sample one action per head
            actions = torch.stack([dist.sample() for dist in dists], dim=-1)  # (B, 3)
        else:
            actions = action

        # logprob = sum of component logprobs
        logprobs = torch.stack(
            [dist.log_prob(actions[:, i]) for i, dist in enumerate(dists)],
            dim=-1
        ).sum(dim=-1)

        entropy = torch.stack(
            [dist.entropy() for dist in dists],
            dim=-1
        ).sum(dim=-1)

        return actions, logprobs, entropy, value


# ------------ Rollout Buffer ------------
class RolloutBuffer:
    def __init__(self, buffer_size, obs_shape, action_dim):
        self.buffer_size = buffer_size
        self.obs = np.zeros((buffer_size, *obs_shape), dtype=np.uint8)
        self.actions = np.zeros((buffer_size, action_dim), dtype=np.int64)
        self.logprobs = np.zeros(buffer_size, dtype=np.float32)
        self.rewards = np.zeros(buffer_size, dtype=np.float32)
        self.dones = np.zeros(buffer_size, dtype=np.float32)
        self.values = np.zeros(buffer_size, dtype=np.float32)

        self.advantages = np.zeros(buffer_size, dtype=np.float32)
        self.returns = np.zeros(buffer_size, dtype=np.float32)
        self.ptr = 0

    def add(self, obs, action, logprob, reward, done, value):
        self.obs[self.ptr] = obs
        self.actions[self.ptr] = action
        self.logprobs[self.ptr] = logprob
        self.rewards[self.ptr] = reward
        self.dones[self.ptr] = float(done)
        self.values[self.ptr] = value
        self.ptr += 1

    def compute_advantages(self, last_value, gamma, gae_lambda):
        adv = 0.0
        for t in reversed(range(self.buffer_size)):
            if t == self.buffer_size - 1:
                next_non_terminal = 1.0
                next_value = last_value
            else:
                next_non_terminal = 1.0 - self.dones[t + 1]
                next_value = self.values[t + 1]

            delta = self.rewards[t] + gamma * next_value * next_non_terminal - self.values[t]
            adv = delta + gamma * gae_lambda * next_non_terminal * adv
            self.advantages[t] = adv

        self.returns = self.advantages + self.values

    def get_batches(self, minibatch_size):
        indices = np.arange(self.buffer_size)
        np.random.shuffle(indices)
        for start in range(0, self.buffer_size, minibatch_size):
            end = start + minibatch_size
            mb_idx = indices[start:end]
            yield mb_idx


# ------------ Training Loop ------------
def train():
    set_seed(0)

    # Create env (for training, do NOT render to save time)
    # If your env is older Gym, it probably uses obs = env.reset()
    env = gym.make(ENV_ID, render_mode=None, is_player_2_computer=True)

    # Handle old vs new reset API:
    reset_result = env.reset()
    if isinstance(reset_result, tuple):
        obs_env, _ = reset_result
    else:
        obs_env = reset_result

    obs_frame = downsample_obs(obs_env)
    frames = deque([obs_frame] * FRAME_STACK, maxlen=FRAME_STACK)
    stacked_obs = stack_frames(frames)
    obs_shape = stacked_obs.shape  # (H, W, C*FRAME_STACK)
    action_dim = len(ACTION_DIMS)

    agent = PikachuPPO(ACTION_DIMS, input_channels=3 * FRAME_STACK).to(DEVICE)
    optimizer = torch.optim.Adam(agent.parameters(), lr=LR_START, weight_decay=1e-5)

    buffer = RolloutBuffer(ROLLOUT_STEPS, obs_shape, action_dim)

    global_step = 0

    for update in trange(1, TOTAL_UPDATES + 1, desc="PPO updates"):
        buffer.ptr = 0

        # Linear annealing for LR and entropy coefficient
        progress = (update - 1) / max(TOTAL_UPDATES - 1, 1)
        slow = min(progress * 0.5, 1.0)  # decay at half speed
        lr_now = LR_START + (LR_END - LR_START) * slow
        ent_coef_now = ENT_COEF_START + (ENT_COEF_END - ENT_COEF_START) * slow
        for g in optimizer.param_groups:
            g['lr'] = lr_now

        for step in trange(ROLLOUT_STEPS, desc="Rollout", leave=False):
            global_step += 1
            env.render()

            # Preprocess observation: uint8 -> float32 in [0,1]
            obs_tensor = obs_to_tensor(stacked_obs).unsqueeze(0)  # (1, H, W, C)

            with torch.no_grad():
                actions_tensor, logprobs_tensor, _, values_tensor = agent.get_action_and_value(obs_tensor)
            action = actions_tensor.squeeze(0).cpu().numpy()           # shape (3,)
            logprob = logprobs_tensor.item()
            value = values_tensor.item()

            # Step environment with action repeat
            total_reward = 0.0
            done = False
            obs_env = None
            for _ in range(ACTION_REPEAT):
                step_result = env.step(action)
                if len(step_result) == 5:
                    # Gymnasium style: obs, reward, terminated, truncated, info
                    next_obs_env, reward, terminated, truncated, info = step_result
                    done = terminated or truncated
                else:
                    # Old Gym style: obs, reward, done, info
                    next_obs_env, reward, done, info = step_result
                total_reward += reward
                obs_env = next_obs_env
                if done:
                    break

            # Downsample next observation for storage / next step
            obs_frame = downsample_obs(obs_env)
            frames.append(obs_frame)
            stacked_obs = stack_frames(frames)

            buffer.add(stacked_obs, action, logprob, total_reward, done, value)

            if done:
                reset_result = env.reset()
                if isinstance(reset_result, tuple):
                    obs_env, _ = reset_result
                else:
                    obs_env = reset_result
                obs_frame = downsample_obs(obs_env)
                frames = deque([obs_frame] * FRAME_STACK, maxlen=FRAME_STACK)
                stacked_obs = stack_frames(frames)

        # Compute last value for GAE
        with torch.no_grad():
            obs_tensor = obs_to_tensor(stacked_obs).unsqueeze(0)
            _, _, _, last_value_tensor = agent.get_action_and_value(obs_tensor)
            last_value = last_value_tensor.item()

        buffer.compute_advantages(last_value, GAMMA, GAE_LAMBDA)

        # Normalize advantages
        adv_mean = buffer.advantages.mean()
        adv_std = buffer.advantages.std() + 1e-8
        buffer.advantages = (buffer.advantages - adv_mean) / adv_std

        # Convert all to torch
        obs_tensor = torch.from_numpy(buffer.obs).to(DEVICE).float() / 255.0  # (N, H, W, C)
        actions_tensor = torch.from_numpy(buffer.actions).to(DEVICE)          # (N, 3)
        old_logprobs_tensor = torch.from_numpy(buffer.logprobs).to(DEVICE)    # (N,)
        returns_tensor = torch.from_numpy(buffer.returns).to(DEVICE)          # (N,)
        advantages_tensor = torch.from_numpy(buffer.advantages).to(DEVICE)    # (N,)
        old_values_tensor = torch.from_numpy(buffer.values).to(DEVICE)        # (N,)

        # PPO updates
        for epoch in trange(PPO_EPOCHS, desc="PPO Epochs", leave=False):
            for mb_idx in buffer.get_batches(MINIBATCH_SIZE):
                mb_obs = obs_tensor[mb_idx]
                mb_actions = actions_tensor[mb_idx]
                mb_old_logprobs = old_logprobs_tensor[mb_idx]
                mb_returns = returns_tensor[mb_idx]
                mb_advantages = advantages_tensor[mb_idx]
                mb_old_values = old_values_tensor[mb_idx]

                _, new_logprobs, entropy, values = agent.get_action_and_value(mb_obs, mb_actions)

                # Ratio
                ratios = (new_logprobs - mb_old_logprobs).exp()

                # PPO loss
                surr1 = ratios * mb_advantages
                surr2 = torch.clamp(ratios, 1.0 - CLIP_EPS, 1.0 + CLIP_EPS) * mb_advantages
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss with clipping
                values_clipped = mb_old_values + (values - mb_old_values).clamp(-VALUE_CLIP, VALUE_CLIP)
                value_loss_unclipped = (values - mb_returns).pow(2)
                value_loss_clipped = (values_clipped - mb_returns).pow(2)
                value_loss = torch.max(value_loss_unclipped, value_loss_clipped).mean()

                # Entropy bonus
                entropy_loss = -entropy.mean()

                loss = policy_loss + VF_COEF * value_loss + ent_coef_now * entropy_loss

                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), MAX_GRAD_NORM)
                optimizer.step()

        # Simple logging
        tqdm.write(
            f"Update {update}/{TOTAL_UPDATES} | Step {global_step} | "
            f"Policy loss: {policy_loss.item():.3f} | "
            f"Value loss: {value_loss.item():.3f} | "
            f"Entropy: {entropy.mean().item():.3f} | "
        )

        # Periodic checkpointing
        if update % 50 == 0:
            os.makedirs("checkpoints", exist_ok=True)
            ckpt_path = f"checkpoints/ppo_pykachu_update_{update}.pt"
            torch.save(agent.state_dict(), ckpt_path)
            tqdm.write(f"Saved checkpoint at {ckpt_path}")

    env.close()

    # Save the trained model
    os.makedirs("checkpoints", exist_ok=True)
    torch.save(agent.state_dict(), "checkpoints/ppo_pykachu.pt")
    print("Saved model to checkpoints/ppo_pykachu.pt")


if __name__ == "__main__":
    train()
