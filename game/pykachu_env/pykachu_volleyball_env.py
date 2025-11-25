import gymnasium as gym
import numpy as np
import pygame

from gymnasium.spaces import MultiDiscrete, Box

from .constants import (
    GROUND_HEIGHT, GROUND_WIDTH, GROUND_HALF_WIDTH, BALL_TOUCHING_GROUND_Y_COORD,
    PLAYER_HALF_LENGTH
)

from .render import GameViewDrawer, Texture
from .physics import PykaPhysics, UserInput

"""
RL environment for 'single' agent. The opponent is the basic AI, originally implemented in the game.
Multi-agent environment using pettingzoo will be added later
"""
class PykachuEnv(gym.Env):
    action_space = MultiDiscrete([3, 3, 2]) 
    """
    (node, left, right), (none, up, down), (none, power hit)
    """
    
    observation_space = Box(low = 0, high = 255, shape=(GROUND_WIDTH, GROUND_HEIGHT, 3),
                            dtype=np.uint8)
    """
    The Space object for all valid observations, corresponding to rendered display of the game(in RGB)
    """                        

    metadata = {'render_modes': ['human']}
    """
    metadata for the environment containing rendering modes, etc 
    """

    def __init__(self, is_player_1_computer= False, is_player_2_computer= False, render_mode= None):
        self.render_mode = render_mode
        self.physics = PykaPhysics(is_player_1_computer, is_player_2_computer)
        self._surface = None
        self._clock = pygame.time.Clock()
        self.is_player_2_computer = is_player_2_computer
        self.is_player_2_serve = False
        self._player1_hit_ball = False
        self._player2_hit_ball = False
        self._last_touch = None  # "p1" | "p2" | None
        self._steps_in_rally = 0
        self._prev_ball_side = None
        self._prev_ball_y_velocity = 0
        return

    @property
    def observation(self):
        if self._surface is None:
            # Training mode: return blank observation
            return np.zeros((432, 304, 3), dtype=np.uint8)
        pixels = pygame.surfarray.pixels3d(self._surface)
        return np.transpose(np.array(pixels), axes=(1, 0, 2))

    def compute_reward(self, action=[0,0,0]):
        base = 0.0
        if self.is_ball_touching_ground:
            if self.physics.ball.punch_effect_x < GROUND_HALF_WIDTH: #player2 wins
                self.is_player_2_serve = True
                base = -1 if self.is_player_2_computer else 1
            else:#player1 wins
                self.is_player_2_serve = False
                base = 1 if self.is_player_2_computer else -1

        ball = self.physics.ball
        player1_x = self.physics.player1.x

        shaping = 0.0
        
        # Efficiency: tiny step penalty to discourage stalling (further softened).
        shaping -= 0.00005 * (1.0 + min(self._steps_in_rally, 400) / 400.0)

        # Positioning: stay close to expected landing on our side; normalize penalty.
        landing_dx = min(abs(ball.expected_landing_x - player1_x), GROUND_HALF_WIDTH)
        if ball.expected_landing_x < GROUND_HALF_WIDTH - 5:
            shaping -= 0.0002 * landing_dx
            if landing_dx < 32:
                shaping += 0.07
            # Bonus for actively moving toward landing spot when not close yet.
            moving_left = (action[0] - 1) < 0
            moving_right = (action[0] - 1) > 0
            if landing_dx > 16:
                if (ball.expected_landing_x < player1_x and moving_left) or \
                   (ball.expected_landing_x > player1_x and moving_right):
                    shaping += 0.015

        # Ball control + Rally pressure: when we hit, reward useful, penalize faults.
        if self._player1_hit_ball:
            shaping += 0.05  # basic contact bonus

            expected_on_opponent = ball.expected_landing_x >= GROUND_HALF_WIDTH + 5
            expected_on_ours = ball.expected_landing_x < GROUND_HALF_WIDTH - 5
            expected_outside_bounds = ball.expected_landing_x < 0 or ball.expected_landing_x > GROUND_WIDTH

            # Defensive save: contact when ball is low and descending on our side.
            low_ball = ball.y > (BALL_TOUCHING_GROUND_Y_COORD - 80)
            descending = self._prev_ball_y_velocity > 0
            on_our_side = ball.x < GROUND_HALF_WIDTH + 4
            if low_ball and descending and on_our_side:
                shaping += 0.08

            # Penalize sending the ball back to our side; reward sending it in-bounds to opponent.
            if expected_on_ours and not expected_outside_bounds:
                shaping -= 0.12
            if expected_on_opponent and not expected_outside_bounds:
                shaping += 0.10

            # Power-hit specific incentives/penalties.
            if action[2] == 1:
                if expected_on_opponent and not expected_outside_bounds:
                    shaping += 0.08
                if expected_on_ours:
                    shaping -= 0.1

        # Penalize being far from a reachable ball on our side.
        if ball.x < GROUND_HALF_WIDTH:
            distance_to_ball = abs(ball.x - player1_x)
            shaping -= 0.00015 * min(distance_to_ball, GROUND_HALF_WIDTH)

        # Penalize ground power-hit/dive when ball is safely away on opponent side or far from us.
        if action[2] == 1:
            ball_on_opponent = ball.expected_landing_x > GROUND_HALF_WIDTH + 5
            far_from_ball = abs(ball.x - player1_x) > 100
            if ball_on_opponent or far_from_ball:
                shaping -= 0.08

            # Penalize rushing into walls/net when already near them.
            x_dir = action[0] - 1  # -1 left, 0 noop, 1 right
            near_left_wall = player1_x < PLAYER_HALF_LENGTH + 8
            near_net = player1_x > GROUND_HALF_WIDTH - 20
            if (near_left_wall and x_dir < 0) or (near_net and x_dir > 0):
                shaping -= 0.05

            # Encourage aerial power hits on our side when ball is reachable above ground.
            player_on_air = self.physics.player1.y < (BALL_TOUCHING_GROUND_Y_COORD - 20)
            ball_on_our_side = ball.x < GROUND_HALF_WIDTH - 5
            ball_high_enough = ball.y < (BALL_TOUCHING_GROUND_Y_COORD - 30)
            if player_on_air and ball_on_our_side and ball_high_enough:
                shaping += 0.08

            # Encourage emergency dives when a low, descending ball is landing on our side and we are far.
            landing_ours = ball.expected_landing_x < GROUND_HALF_WIDTH - 5
            low_and_descending = ball.y > (BALL_TOUCHING_GROUND_Y_COORD - 60) and ball.y_velocity > 0
            far_reach = abs(ball.x - player1_x) > 48
            if landing_ours and low_and_descending and far_reach:
                shaping += 0.12

        # Net-camping penalty: discourage hugging the net when ball is safely on opponent side.
        if ball.x > GROUND_HALF_WIDTH + 10 and ball.expected_landing_x > GROUND_HALF_WIDTH + 20:
            if player1_x > GROUND_HALF_WIDTH - 28:
                shaping -= 0.1  # stronger deterrent near net
                shaping -= 0.002 * (player1_x - (GROUND_HALF_WIDTH - 28))  # scaled penalty further in

        # Jump spam penalty: avoid repeated jumps near net when ball is far away.
        if ball.x > GROUND_HALF_WIDTH + 10:
            if self.physics.player1.state in (1, 2):  # jumping / jump power-hit
                shaping -= 0.03

        # Encourage neutral standby away from net when waiting on opponent side.
        if ball.x > GROUND_HALF_WIDTH + 10 and ball.expected_landing_x > GROUND_HALF_WIDTH + 20:
            if player1_x < GROUND_HALF_WIDTH - 50:  # staying back a bit
                shaping += 0.02


        # Keep shaping bounded so terminal reward dominates.
        shaping = float(np.clip(shaping, -0.15, 0.5))
        

        return base + shaping


    @property
    def terminated(self):
        return self.is_ball_touching_ground

    @property
    def info(self):
        player1 = self.physics.player1
        player2 = self.physics.player2
        ball = self.physics.ball
        return {
            "player1": {
                "x": player1.x,
                "y": player1.y,
                "dive_direction" : player1.dive_direction 
            },
            "player2":{
                "x": player2.x,
                "y": player2.y,
                "dive_direction" : player2.dive_direction 
            },
            "ball": {
                "x": ball.x,
                "x_velocity": ball.x_velocity,
                "y": ball.y,
                "y_velocity": ball.y_velocity,
            }
        }

    def step(self, action):
        player1_input = UserInput(action)
        player2_input = UserInput(action)

        ball = self.physics.ball
        self._prev_ball_side = "p1_side" if ball.x < GROUND_HALF_WIDTH else "p2_side"
        self._prev_ball_y_velocity = ball.y_velocity

        self.is_ball_touching_ground = self.physics.run_engine([player1_input, player2_input])
        self._player1_hit_ball = self.physics.player1.is_ball_collision_happened
        self._player2_hit_ball = self.physics.player2.is_ball_collision_happened

        if self._player1_hit_ball:
            self._last_touch = "p1"
        elif self._player2_hit_ball:
            self._last_touch = "p2"

        if self.is_ball_touching_ground:
            if self.physics.ball.punch_effect_x < GROUND_HALF_WIDTH: #player2 wins
                self.is_player_2_serve = True
            else:#player1 wins
                self.is_player_2_serve = False
 
        self._steps_in_rally += 1

        return self.observation, self.compute_reward(action), self.terminated, self.info


    def render(self):
        if self._surface is None:
            pygame.init()

            if self.render_mode == 'human':
                pygame.display.init()
                self._surface = pygame.display.set_mode((GROUND_WIDTH, GROUND_HEIGHT))
                pygame.display.set_caption('Pykachu Volleyball')
                self.texture = Texture()
                self.view = GameViewDrawer(self.texture)

            elif self.render_mode == "rgb_array":
                return self.observation
            
        # Draw
        if self.render_mode == 'human':
            pygame.event.pump()
            self.view.draw_background()
            self.view.draw_players_and_ball(self.physics) 
            pygame.display.update()
            self._clock.tick(25)

    def reset(self, seed = None):
        super().reset(seed = seed)

        self.physics.reset(self.is_player_2_serve)
        self.is_ball_touching_ground = False
        self._player1_hit_ball = False
        self._player2_hit_ball = False
        self._last_touch = None
        self._steps_in_rally = 0
        self._prev_ball_side = None
        self._prev_ball_y_velocity = 0

        if self.render_mode is not None:
            self.render()

        return self.observation, self.info
    
