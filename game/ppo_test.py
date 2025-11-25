import gymnasium as gym
import pygame
import torch
import numpy as np
import pykachu_env

import ppo_agent
from collections import deque

pygame.init()

MODEL_PATH = "checkpoints/ppo_pykachu_update_50.pt"  # change to a specific checkpoint if desired
ACTION_REPEAT_TEST = 1  # smaller repeat to slow down play

env = gym.make("PykachuVolleyball-v0", render_mode="human", is_player_1_computer=False, is_player_2_computer=True)
reset_result = env.reset()
if isinstance(reset_result, tuple):
    obs_env, _ = reset_result
else:
    obs_env = reset_result

# Build initial frame stack
obs_frame = ppo_agent.downsample_obs(obs_env)
frames = deque([obs_frame] * ppo_agent.FRAME_STACK, maxlen=ppo_agent.FRAME_STACK)
stacked_obs = ppo_agent.stack_frames(frames)

agent = ppo_agent.PikachuPPO(ppo_agent.ACTION_DIMS, input_channels=3 * ppo_agent.FRAME_STACK).to(ppo_agent.DEVICE)
agent.load_state_dict(torch.load(MODEL_PATH, map_location=ppo_agent.DEVICE))
agent.eval()

running = True
clock = pygame.time.Clock()

while running:
    clock.tick(60)  # lower FPS to slow down gameplay

    env.render()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    obs_tensor = ppo_agent.obs_to_tensor(stacked_obs).unsqueeze(0)

    with torch.no_grad():
        actions, _, _, _ = agent.get_action_and_value(obs_tensor)
    action = actions.squeeze(0).cpu().numpy()

    # Repeat the chosen action; test uses smaller repeat to slow things down
    done = False
    for _ in range(ACTION_REPEAT_TEST):
        step_result = env.step(action)
        if len(step_result) == 5:
            obs_env, reward, terminated, truncated, info = step_result
            done = terminated or truncated
        else:
            obs_env, reward, done, info = step_result
        if done:
            break
    print(action, reward)
    if done:
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            obs_env, _ = reset_result
        else:
            obs_env = reset_result
        # reset frame stack on episode reset
        obs_frame = ppo_agent.downsample_obs(obs_env)
        frames = deque([obs_frame] * ppo_agent.FRAME_STACK, maxlen=ppo_agent.FRAME_STACK)
        stacked_obs = ppo_agent.stack_frames(frames)
        continue
    
    # update frame stack with new observation
    obs_frame = ppo_agent.downsample_obs(obs_env)
    frames.append(obs_frame)
    stacked_obs = ppo_agent.stack_frames(frames)

env.close()
pygame.quit()
