import spotipy, time, asyncio, random, subprocess, glob, json, os, requests
from threading import Thread
from spotipy.oauth2 import SpotifyOAuth
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json

os.chdir('/home/pi/Python/music-and-light')

hosts = ['ip1', 'ip2']

hues = list(range(0, 360, 30))
saturations = list(range(50, 101, 10))

cid = 'xxx'
secret = 'xxx'
redirect_uri = "xxx"
scope = "user-read-playback-state"
spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=cid, client_secret=secret, redirect_uri=redirect_uri, scope=scope))

# global variables for currnet playback info
track, track_id, progress = None, None, None

def random_hue(exclusion):
    return random.choice([hue for hue in hues if hue not in exclusion])

def random_saturation():
    return random.choice(saturations)

def get_track_info(artist_name, track_name):
    driver.find_elements(By.XPATH, '//*[@id="search-form"]/input')[0].send_keys(f"{artist_name} - {track_name}")
    driver.find_elements(By.XPATH, '//*[@id="search-form"]/input')[0].send_keys(Keys.RETURN)
    
    duration = driver.find_elements(By.XPATH, '/html/body/div[1]/main/div[2]/div[2]/a/div[2]/div[2]/span[2]')[0].text
    [minutes, seconds] = duration.split(':')
    duration = int(minutes) * 60 + int(seconds)

    bpm = int(driver.find_elements(By.XPATH, '/html/body/div[1]/main/div[2]/div[2]/a/div[2]/div[3]/span[2]')[0].text)
    print(f"{artist_name} - {track_name}: {duration}s, {bpm}bpm")
    return duration, bpm

def get_song_info(allow_shutdown=True):
    global track, track_id, progress
    duration, bpm = None, None

    nothing_is_playing = True
    wait_start_time = time.time()
    while True:
        track = spotify.current_playback()
        if (track is None) or (not track['is_playing']) or (track['device']['name'] != 'Kitchen Speaker'):
            time.sleep(1.5)
        else:
            nothing_is_playing = False
            break
        if (time.time() - wait_start_time >= 60):
            break
    
    if allow_shutdown and nothing_is_playing:
        # exucute the stop procedure (in bash)
        subprocess.Popen('./stop', shell=True, stdout=subprocess.DEVNULL, executable="/bin/bash")
        exit()
    elif allow_shutdown:
        if track is not None:
            item = track['item']
            track_id = item['id']
            progress = round(track['progress_ms'] / 1000, 2)

            # first, read from local track info file if it is available
            # if not, query spotify and save the result
            if track_id in track_info_dict:
                duration = track_info_dict[track_id]['duration']
                bpm = track_info_dict[track_id]['bpm']
            else:
                duration = 240
                bpm = 120
                for retry in range(10):
                    duration, bpm = get_track_info(artist_name=item['artists'][0]['name'], track_name=item['name'])
                    if (duration is not None) and (bpm is not None):
                        track_info_dict[track_id] = {}
                        track_info_dict[track_id]['artist'] = item['artists'][0]['name']
                        track_info_dict[track_id]['track'] = item['name']
                        track_info_dict[track_id]['duration'] = duration
                        track_info_dict[track_id]['bpm'] = bpm

                        # add track info to the output of audio analysis
                        with open('track_info.json', "w") as file:
                            json.dump(track_info_dict, file, ensure_ascii=False, indent=4)
                        break
                    else:
                        time.sleep(1)
    
    return track, track_id, progress, duration, bpm

def get_song_info_loop():
    while True:
        try:
            get_song_info(allow_shutdown=False)
        except Exception as e:
            print('Error in get_song_info_loop')
            print(e)
        time.sleep(1.5)

async def change_color(host, h, s=100, v=50, transition=0):
    subprocess.Popen(f'kasa --type bulb --host {host} hsv {h} {s} {v} --transition {transition}', shell=True, stdout=subprocess.DEVNULL, executable="/bin/bash")

async def change_color_x2(hosts, h, s=100, v=50, transition=0):
    subprocess.Popen(f'kasa --type bulb --host {hosts[0]} hsv {h} {s} {v} --transition {transition} & kasa --type bulb --host {hosts[1]} hsv {h} {s} {v} --transition {transition}', shell=True, stdout=subprocess.DEVNULL, executable="/bin/bash")

if __name__ == "__main__":

    with open('track_info.json', 'r') as file:
        track_info_dict = json.load(file)

    service = Service('/usr/bin/chromedriver')
    options = Options()
    options.add_argument('--headless=new')
    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://songbpm.com/")

    # daemon thread to repeatedly get current spotify playback status
    p = Thread(name="get_song_info_loop", target=get_song_info_loop)
    p.daemon = True
    p.start()

    # the hues to exclude from the next draw, in order not to have the same color twice consecutively
    exclusion = []

    # loop over songs
    while True:
        try:
            # get song info
            track, track_id, progress, duration, bpm = get_song_info(allow_shutdown=True)

            # preserve the original values before they get updated
            current_track_id = track_id
            current_offset = progress
            playtime = current_offset
            
            # time 0
            start_time = time.time()
            
            fadeout = False
            count_short = 0
            count_long = 0

            # loop over time intervals
            while True:
                # for any reason a reset is needed
                # e.g., not playing, paused, not playing on the right speaker, new song starting, current song ending, current playtime too different from progress
                if (track is None) or (not track['is_playing']) or (track_id != current_track_id) or (playtime >= duration) or (track['device']['name'] != 'Kitchen Speaker'):
                    break
                # fadeout mode
                elif (playtime >= duration - 10) and (not fadeout):
                    asyncio.run(change_color_x2(hosts, h=30, s=1, v=10, transition=5000))
                    fadeout = True
                else:
                    # a new section
                    if count_long == 0:
                        # set highlight color
                        asyncio.run(change_color_x2(hosts, h=0, s=0, v=90))
                        time.sleep(60 / bpm * 8)
                    # a new beat
                    else:
                        # set random hue and saturation
                        h = random_hue(exclusion=exclusion)
                        s = random_saturation()
                        asyncio.run(change_color(hosts[count_short], h=h, s=s))
                        exclusion.append(h)
                        exclusion = exclusion[-2:]
                        time.sleep(60 / bpm * 2)
                                   
                    count_short = (count_short + 1) % 2
                    count_long = (count_long + 1) % 16
                    
                playtime = round(time.time() - start_time + current_offset)
                time.sleep(0.001)
        except Exception as e:
            print('Error in main loop')
            print(e)
            time.sleep(10)
