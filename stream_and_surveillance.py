# -*- coding: utf-8 -*-
"""
Created on 05/2021

@author: 23

@desc: Version finale du programme de diffusion et de surveillance serveur
"""

import os
import sys
import time
import datetime

import threading

import socket
import errno
import urllib.request

import numpy as np

import imageio
import cv2

import imutils



class Server():
    """Classe d'instance de diffusion et de surveillance."""
    def __init__(self, source, port):
        #Reception du flux (source:port, data)
        self.source_url = source
        self.port = port
        self.source = None
        self.data = b''

        self.prefix = "[STREAM PORT " + str(self.port) + "]"

        #Client serveur (socket, client)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(0.01)
        self.socket.bind(("0.0.0.0", self.port))
        self.socket.listen(1)
        self.client = None

        #Surveillance
        self.img_reference = None
        self.detected = False
        self.last_presence_time = None
        self.recording = False
        self.frames_to_save = []
        self.thread_save_record = threading.Thread(target=self.save_record, args=(), daemon=True)

    def broadcast_and_watch(self):
        """Fonction de diffusion par socket et de surveillance du flux vidéo."""
        print(str(self.prefix) + "[START] Broadcast and surveillance start for " + str(self.source_url) + " on port " + str(self.port))
        while True:
            if self.source is None:
                try:
                    self.source = urllib.request.urlopen(self.source_url, timeout=1)
                    print(str(self.prefix) + "[INFO] Source connected !")
                except Exception as err_source:
                    print(str(self.prefix) + "[Error from video source] : " + str(err_source))
                    self.source = None
                    print(str(self.prefix) + "[INFO] Retry to connect to source in 5 seconds...")
                    time.sleep(5)
            else:
                try:
                    self.data += self.source.read(512)
                except socket.timeout:
                    pass
                except KeyboardInterrupt:
                    print(str(self.prefix) + "[ALERT] Script stopped by user...")
                    self.client.close()
                    self.client = None
                    self.source.close()
                    sys.exit()
                except OSError as os_err:
                    print(str(self.prefix) + "[OS Error] " + str(os_err))
                    print(str(self.prefix) + "[ALERT] Stream aborted !")
                    self.socket.close()
                    if len(self.frames_to_save) > 0:
                        self.thread_save_record.start()
                        while len(threading.enumerate()) > 1:
                            time.sleep(1)
                    break
                except Exception as err:
                    print(str(self.prefix) + "[ERROR] Other error : " + str(err))
                    self.client.close()
                    self.client = None
                    self.source.close()
                    sys.exit()
                else:
                    img_start = self.data.find(b'\xff\xd8')
                    img_end = self.data.find(b'\xff\xd9')
                    if img_start > -1 and img_end > -1:
                        try:
                            extracted_img = self.data[img_start:img_end+2]
                            self.data = self.data[img_end+2:]
                            jpg = cv2.imdecode(np.frombuffer(extracted_img, dtype='int8'), cv2.IMREAD_COLOR)
                            gray = cv2.cvtColor(jpg, cv2.COLOR_BGR2GRAY)
                            gray = cv2.GaussianBlur(gray, (21, 21), 0)
                            if self.img_reference is None:
                                self.img_reference = gray
                                continue
                            frame_delta = cv2.absdiff(self.img_reference, gray)
                            thresh = cv2.threshold(frame_delta, 50, 255, cv2.THRESH_BINARY)[1]
                            thresh = cv2.dilate(thresh, None, iterations=2)
                            cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                            cnts = imutils.grab_contours(cnts)
                            for c in cnts:
                                # if the contour is too small, ignore it
                                if cv2.contourArea(c) < 500:
                                    if self.detected:
                                        self.detected = False
                                    continue
                                self.detected = True
                                self.last_presence_time = datetime.datetime.now()
                                #Si une présence est detectée, mise en route si necessaire de l'enregistrement
                                if self.detected:
                                    if not self.recording:
                                        print(str(self.prefix) + "[INFO] Presence detected ! Start record")
                                        self.recording = True
                            #Si l'option "enregistrement" est activée, on conserve l'image courante
                            if self.recording:
                                self.frames_to_save.append(cv2.cvtColor(jpg, cv2.COLOR_BGR2RGB))
                                if int((datetime.datetime.now()- self.last_presence_time).total_seconds()) == 5:
                                    print(str(self.prefix) + "[INFO] Nothing detected since 5 seconds, stop record...")
                                    self.thread_save_record.start()
                                elif len(self.frames_to_save) >= 1000:
                                    print(str(self.prefix) + "[INFO] More than 1000 frames recorded, save...")
                                    self.img_reference = gray
                                    self.thread_save_record.start()
                            to_send = str.encode("camera:" + str(self.port) + ";timestamp:" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + ";record:" + str(self.recording)) + extracted_img
                        except cv2.error:
                            pass
                        if len(self.data) > 10000:
                            print(str(self.prefix) + "[ALERT] Variable too large (over 10000)")
                            self.data = b''
                        elif len(self.data) > 8000:
                            print(str(self.prefix) + "[ALERT] Variable large (over 8000)")
                            self.data = b''

                        if self.client is None:
                            try:
                                self.client, address = self.socket.accept()
                                print(str(self.prefix) + "[INFO] New client : " + str(address))
                            except socket.timeout:
                                self.client = None
                                continue
                        else:
                            try:
                                self.client.send(to_send)
                            except KeyboardInterrupt:
                                print(str(self.prefix) + "[ALERT] Stream shutdown by user...")
                                if not self.client is None:
                                    self.client.close()
                                    self.socket.close()
                                    sys.exit()
                            except socket.error as s_err:
                                if s_err.errno == errno.ECONNRESET:
                                    print(str(self.prefix) + "[INFO] Client disconnected...")
                                else:
                                    print(str(self.prefix) + "[ERROR] Socket error : " + str(s_err))
                                    self.client.close()
                                    self.client = None

    def save_record(self):
        """ Arrete l'enregistrement et sauvegarde les images récupérées en vidéo """
        self.recording = False
        self.thread_save_record = threading.Thread(target=self.save_record, args=(), daemon=True)
        frames = self.frames_to_save
        print(str(self.prefix) + "[INFO] Stop recording, saving " + str(len(frames)) + " frame(s)...")
        now = str(datetime.datetime.now().strftime("%Y-%m-%d-%H_%M_%S"))
        filename = "rec-" + str(now) + ".mp4"
        if not os.path.isdir("./storage/"):
            try:
                os.mkdir("./storage/")
                print(str(self.prefix) + "[INFO] Created storage directory")
            except OSError as os_exception:
                print(str(self.prefix) + "[ERROR] OS error detected : " + str(os_exception))
        if not os.path.isdir("./storage/records/"):
            try:
                os.mkdir("./storage/records/")
                print(str(self.prefix) + "[INFO] Created video record directory")
            except OSError as os_exception:
                print(str(self.prefix) + "[ERROR] OS error detected : " + str(os_exception))
        writer = imageio.get_writer('storage/records/'+filename, format='mp4', mode='I', fps=26)
        for frame in frames:
            writer.append_data(frame)
        writer.close()
        print(str(self.prefix) + "[INFO] Record saved as : " + str(filename) + " in records directory.")
        self.frames_to_save.clear()

def main():
    """Fonction principale : Vérification des arguments et démarrage d'une instance serveur."""
    if len(sys.argv) == 5:
        for i in range(1, len(sys.argv)):
            if i % 2 == 1:
                if sys.argv[i] == "--url":
                    if isinstance(sys.argv[i + 1], str):
                        source_url = sys.argv[i+1]
                    else:
                        print("--url must be string")
                        sys.exit()
                elif sys.argv[i] == "--port" or sys.argv[i] == "-p":
                    if sys.argv[i + 1].isdigit():
                        broadcast_port = int(sys.argv[i+1])
                    else:
                        print("--port must be int")
                        sys.exit()
    else:
        print("Usage : stream_and_surveillance.py --url <link> --port <800X>")
        sys.exit()
    server = Server(source_url, broadcast_port)
    server.broadcast_and_watch()
    del server

if __name__ == '__main__':
    main()
