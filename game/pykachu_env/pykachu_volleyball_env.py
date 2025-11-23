import gymnasium as gym
import numpy as np
import pygame

from gymnasium.spaces import MultiDiscrete, Box

from .constants import (
    GROUND_HEIGHT, GROUND_WIDTH, GROUND_HALF_WIDTH
)

from .render import GameViewDrawer, Texture
from .physics import PykaPhysics, UserInput, let_computer_decide_user_input

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
        self._imitation_bonus = 0.0
        return

    @property
    def observation(self):
        if self._surface is None:
            # Training mode: return blank observation
            return np.zeros((432, 304, 3), dtype=np.uint8)
        pixels = pygame.surfarray.pixels3d(self._surface)
        return np.transpose(np.array(pixels), axes=(1, 0, 2))

    @property
    def reward(self):
        base = 0.0
        if self.is_ball_touching_ground:
            if self.physics.ball.punch_effect_x < GROUND_HALF_WIDTH: #player2 wins
                self.is_player_2_serve = True
                base = -1 if self.is_player_2_computer else 1
            else:#player1 wins
                self.is_player_2_serve = False
                base = 1 if self.is_player_2_computer else -1

        # Shaping: reward ball contacts, gently encourage positioning to expected landing.
        # Note: values are kept small so terminal rewards dominate.
        hit_bonus = 0.05 if self._player1_hit_ball else 0.0

        ball = self.physics.ball
        player1_x = self.physics.player1.x

        # Distance to where the ball is expected to land (clipped for stability)
        landing_dx = min(abs(ball.expected_landing_x - player1_x), GROUND_HALF_WIDTH)
        if landing_dx < GROUND_HALF_WIDTH:
            positioning_penalty = -0.0005 * landing_dx
            proximity_bonus = 0.02 if landing_dx < 20 else 0.0
        else:
            positioning_penalty = 0.0
            proximity_bonus = 0.0

        return base + hit_bonus + positioning_penalty +proximity_bonus + self._imitation_bonus


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
        # Compute heuristic "teacher" action for player1 to shape reward
        teacher_input = UserInput()
        let_computer_decide_user_input(
            self.physics.player1,
            self.physics.ball,
            self.physics.player2,
            teacher_input
        )
        teacher_action = np.array(
            [teacher_input.x_direction + 1, teacher_input.y_direction + 1, teacher_input.power_hit],
            dtype=np.int64
        )
        
        player1_input = UserInput(action)
        player2_input = UserInput(action)

        self.is_ball_touching_ground = self.physics.run_engine([player1_input, player2_input])
        self._player1_hit_ball = self.physics.player1.is_ball_collision_happened

        # Imitation bonus: small reward when agent action matches heuristic
        match = (teacher_action == np.array(action)).astype(np.float32)
        self._imitation_bonus = 0.02 * 1 if match.mean() == 1 else 0.0

        if self.is_ball_touching_ground:
            if self.physics.ball.punch_effect_x < GROUND_HALF_WIDTH: #player2 wins
                self.is_player_2_serve = True
            else:#player1 wins
                self.is_player_2_serve = False
 
        return self.observation, self.reward, self.terminated, self.info


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

        if self.render_mode is not None:
            self.render()

        return self.observation, self.info
    
