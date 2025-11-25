import gymnasium as gym
import pygame
import pykachu_env


pygame.init()

is_player_2_computer=True

env = gym.make("PykachuVolleyball-v0", render_mode="human", is_player_2_computer=True)
obs, info = env.reset()

running = True
clock = pygame.time.Clock()

score = [0, 0]

while running:
    clock.tick(50)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    env.render()

    keys = pygame.key.get_pressed()

    # Action format: [left/right, up/down, power]
    # [0=left,1=stay,2=right], [0=up,1=stay,2=down], [0=no power,1=power]
    action = [1, 1, 0]

    if keys[pygame.K_LEFT]:
        action[0] = 0
    elif keys[pygame.K_RIGHT]:
        action[0] = 2

    if keys[pygame.K_UP]:
        action[1] = 0
    elif keys[pygame.K_DOWN]:
        action[1] = 2

    if keys[pygame.K_SPACE]:
        action[2] = 1

    obs, reward, done, info = env.step(action)
    

    # Reset round when someone scores
    if done:
        obs = env.reset()
        
        if(info["ball"]["x"]>216):
                score[0]+=1
        else:
                score[1]+=1
        print(f"Score player1:{score[0]} player2:{score[1]}")

env.close()
pygame.quit()
