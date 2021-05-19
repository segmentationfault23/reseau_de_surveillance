# -*- coding: utf-8 -*-
"""
Created on 05/2021

@author: 23

@desc: Version finale de l'application client.\
       L'application est capable de visionner les différentes caméras \
       et de se connecter au stockage du serveur.
"""

import os
import datetime
import time
import threading
import socket
import urllib
import tkinter as tki  # Librairie pour la création de l'interface
from ftplib import FTP # Librairie de connexion au stockage serveur
import numpy as np

# Librairies pour le traitement d'image (OpenCV, PIL)
from PIL import Image
from PIL import ImageTk
import imageio         # Librairie de création des fichiers vidéo
import cv2

class CameraMonitorApp():
    """Classe de l'application client."""

    def __init__(self):
        """Initialise la classe, création de l'interface."""
        # Je crée une interface TKinter (Taille fixe, nom, icone)
        self.root = tki.Tk()
        self.root.resizable(False, False)
        self.root.wm_title("Camera network monitor v3.3")
        self.root.iconbitmap('media/ip.ico')
        # Si une fermeture de la fenetre est detectée, declencher la fonction de fermeture "propre"
        self.root.wm_protocol("WM_DELETE_WINDOW", func=self.on_close)
        #Création des widgets (Panneau + 3 boutons) dans un tableau
        self.widgets = []
        # Panneau qui servira à afficher l'image de la caméra
        self.widgets.append( \
            tki.Label(image=ImageTk.PhotoImage(Image.new("RGB", [300, 300])), bg="black"))
        #Bouton prise de photo
        self.widgets.append( \
            tki.Button(self.root, text="Photo",\
                       state="disabled", command=self.take_picture))
        self.widgets.append( \
            tki.Button(self.root, text="<", state="disabled", \
            command=lambda: self.change_source("previous")))
        self.widgets.append( \
            tki.Button(self.root, text=">", state="disabled", \
            command=lambda: self.change_source("next")))
        self.widgets.append( \
            tki.Button(self.root, text="RELOAD", state="disabled"))
        #Menu pour les différentes commandes (options, enregistrement)
        self.widgets.append(tki.Menu(self.root))
        menu_file = tki.Menu(self.widgets[2], tearoff=0)
        menu_record = tki.Menu(self.widgets[2], tearoff=0)
        menu_file.add_command(label="Quitter", command=lambda: self.on_close())
        menu_record.add_command(label="Demarrer l'enregistrement", command=self.record)
        menu_record.add_command(label="Arrêter l'enregistrement", \
                                command=lambda: self.thread_save_record.start())
        menu_record.add_command(label="Consulter les enregistrements", \
                                command=lambda: self.thread_ftp.start())
        self.widgets[5].add_cascade(label="Fichier", menu=menu_file)
        self.widgets[5].add_cascade(label="Enregistrement", menu=menu_record)
        #Organisation des widgets
        self.widgets[0].grid(row=1, column=1, columnspan=4)
        self.widgets[1].grid(row=2, column=1, columnspan=1)
        self.widgets[2].grid(row=2, column=2, columnspan=1)
        self.widgets[3].grid(row=2, column=3, columnspan=1)
        self.widgets[4].grid(row=2, column=4, columnspan=1)
        self.root.config(menu=self.widgets[5])

        self.video_source = []
        self.current_video_source = None
        self.data_stream = b''
        self.frame = None
        self.thread = None
        self.thread_save_record = None
        self.frames_to_save = []
        self.recording = False
        self.fps = 30

        self.ftp_server = None
        self.ftp_window = None

        """
        La fonction d'acquisition de l'image sera placée dans un thread exécuté en boucle.
        """
        self.thread = threading.Thread(target=self.__get_videostream, args=(), daemon=True)
        self.thread_save_record = threading.Thread(target=self.save_record, args=(), daemon=True)
        self.thread_ftp = threading.Thread(target=self.get_storage, args=(), daemon=True)
        #Cette variable servira a arreter le thread d'acquisition depuis l'exterieur de celui-ci
        self.stop_thread = False
    def __get_videostream(self):
        """Acquisition et affichage de l'image de la camera."""
        while True:
            # Si la variable d'arret du thread est définie (TRUE), on arrete le programme
            if self.stop_thread:
                print("[INFO] Arret du fil d'acquisition...")
                break
            #S'il n'existe aucune source vidéo, les repérer
            if len(self.video_source) == 0:
                self.video_source = self.find_video_sources()
            #Si aucune source n'est affichée à l'écran, prendre la première disponible
            elif self.current_video_source is None:
                self.current_video_source = self.video_source[0]
                start = time.time()
                i = 0
                #Activer les boutons de changements de source s'il existe plus d'une source
                if len(self.video_source) > 1:
                    #Bouton "source precédente"
                    if self.widgets[2]["state"] == "disabled":
                        self.widgets[2].config(state="normal")
                    #Bouton "source suivante"
                    if self.widgets[3]["state"] == "disabled":
                        self.widgets[3].config(state="normal")
                else:
                    self.widgets[2].config(state="disabled")
                    self.widgets[3].config(state="disabled")
            else:
                #Lecture du flux vidéo
                try:
                    self.data_stream += self.current_video_source.recv(4096)
                except Exception:
                    #On reintialise la source vidéo si une erreur est detectée lors de la lecture
                    print('[ALERT] Source vidéo actuelle perdue...')
                    self.current_video_source.close()
                    self.video_source.remove(self.current_video_source)
                    self.current_video_source = None
                    no_image = ImageTk.PhotoImage(Image.new("RGB", [300, 300]))
                    self.widgets[0].configure(image=no_image)
                    self.widgets[0].image = no_image
                    self.data_stream = b''
                    if self.widgets[1]["state"] == "normal":
                        self.widgets[1].config(state="disabled")
                    continue
                else:
                    #On recherche les marqueurs de début et de fin de l'image
                    img_start = self.data_stream.find(b'\xff\xd8')
                    img_end = self.data_stream.find(b'\xff\xd9')
                    if img_start > -1 and img_end > -1:
                        metadatas = self.data_stream[0:img_start].decode().split(";")
                        #Calcul du nombre d'image par secondes (sur une échantillion de 60 images)
                        if i < 60:
                            i += 1
                        else:
                            end = time.time()
                            self.fps = 60 / (end - start)
                            i = 0
                            start = time.time()
                        #On conserve le contenu de l'image
                        jpg = self.data_stream[img_start:img_end+2]
                        #Et on soustrait ces données au flux de donnée récupérées
                        self.data_stream = self.data_stream[img_end+2:]
                        try:
                            if self.recording:
                                self.frames_to_save.append(np.frombuffer(jpg, dtype='int8'))
                            #Conversion des données de l'image en matrice avec OpenCV
                            jpg = cv2.imdecode(np.frombuffer(jpg, dtype='int8'), cv2.IMREAD_COLOR)
                            #Les couleurs de l'image étant mal-étalonnées (BGR)
                            #On les réétalonne BGR vers RGB
                            self.frame = cv2.cvtColor(jpg, cv2.COLOR_BGR2RGB)
                            if self.recording:
                                self.frames_to_save.append(self.frame)
                                cv2.putText(self.frame, "RECORDING...", (10, 20), \
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                            metadatas_text = "Port " + str(metadatas[0].split(':')[1]) + " - " + str(metadatas[1].split('timestamp:')[1])
                            cv2.putText(self.frame, metadatas_text, ((10, 480 - 30)), \
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                            #L'image étant sous forme de matrice, on la convertie en image PIL
                            image = Image.fromarray(self.frame)
                            #On redimensionne l'image
                            ratio = image.size[0]/float(image.size[1])
                            image = image.resize((720, int(720/float(ratio))), Image.ANTIALIAS)
                            #Enfin, on convertie en PhotoImage PIL pour pouvoir l'afficher
                            image = ImageTk.PhotoImage(image)

                            #Mise a jour de l'image affichée à l'écran
                            self.widgets[0].configure(image=image)
                            self.widgets[0].image = image
                            #Réactivation du bouton de prise de photo si besoin
                            if self.widgets[1]["state"] == "disabled":
                                self.widgets[1].config(state="normal")
                        except cv2.error:
                            #On abandonne le traitement de l'image par openCV si en cas d'erreur
                            continue
                        except socket.timeout:
                            #On ignore les temps mort du socket
                            pass
    def find_video_sources(self):
        """Scan les ports disponibles sur le serveur 8001 - 8010."""
        start_scan = time.time()
        print("[INFO] Recherche de sources vidéo...")
        ports_ok = []
        sources_ok = []
        for port in range(8001, 8005):
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                test_socket.connect(("_._._._", port))
            except Exception:
                test_socket.close()
                continue
            else:
                test_socket.settimeout(1)
                ports_ok.append(port)
                sources_ok.append(test_socket)
        print("[INFO] Port(s) open : " + str(ports_ok) + " ; total : " + str(len(ports_ok)))
        print("in " + str(time.time() - start_scan) + " seconds")
        return sources_ok
    def change_source(self, command):
        """Basculer d'une source vidéo à une autre."""
        print("[INFO] Changement de source...")
        print(str(len(self.video_source)) + " available source(s)")
        current_source_index = self.video_source.index(self.current_video_source)
        if len(self.video_source) > 0:
            #Si appui sur le bouton "Source précédente"
            if command == "previous":
                #Retour à la fin, pour eviter l'index négatif
                if current_source_index - 1 < 0:
                    self.current_video_source = self.video_source[-1]
                else:
                    self.current_video_source = self.video_source[current_source_index - 1]
            #Si appui sur le bouton "Source suivante"
            elif command == "next":
                #Retour au début, pour eviter l'index hors tableau
                if current_source_index + 1 == len(self.video_source):
                    self.current_video_source = self.video_source[0]
                else:
                    self.current_video_source = self.video_source[current_source_index + 1]

    def take_picture(self):
        """ Capture de l'image courante pour l'enregistrer """
        #On commence par vérifier que la source est active et que l'image affiché est valide
        if not self.current_video_source is None and isinstance(self.frame, np.ndarray):
            now = str(datetime.datetime.now().strftime("%Y-%m-%d-%H_%M_%S"))
            directory = "./captures/"
            filename = "pic-" + str(now) + ".png"
            #Verification de l'existence du dossier d'enregistrement
            if not os.path.isdir(directory):
                try:
                    os.mkdir(directory)
                except OSError as os_exception:
                    print("[ERROR] OS error detected : " + str(os_exception))
            #Enregistrement et affichage de l'image actuelle
            frame_to_save = Image.fromarray(self.frame)
            frame_to_save.save(directory + filename, format="png")
            frame_to_save.show()
            print("[INFO] Save of current picture as : " + \
                  str(filename) + " in captures directory.")
        else:
            print("[ERROR] Invalid current image or inactive video source")

    def on_close(self):
        """Arret propre du programme pour vider les variables et arreter l'application."""
        print("[INFO] Arret de l'application")
        # Vérification de l'existence existence d'une source video et arret
        if not self.current_video_source is None:
            self.current_video_source = None
        for source in self.video_source:
            source.close()
        self.video_source.clear()
        if self.recording:
            self.thread_save_record.start()
        self.stop_thread = True
        self.root.quit()
        self.root.destroy()
    def record(self):
        """Active le mode enregistrement."""
        if self.recording:
            print("[INFO] Déjà entrain d'enregistrer...")
        else:
            print("[INFO] Début de l'enregistrement...")
            self.recording = True
    def save_record(self):
        """Arrete l'enregistrement et sauvegarde les images récupérées en vidéo."""
        self.recording = False
        frames = self.frames_to_save
        print("[INFO] Stop recording, saving " + str(len(frames)) + " frame(s)...")
        print("[INFO] FPS = " + str(self.fps))
        now = str(datetime.datetime.now().strftime("%Y-%m-%d-%H_%M_%S"))
        filename = "rec-" + str(now) + ".mp4"
        if not os.path.isdir("./records/"):
            try:
                os.mkdir("./records/")
                print("[INFO] Created video record directory")
            except OSError as os_exception:
                print("[ERROR] OS error detected : " + str(os_exception))
        #
        writer = imageio.get_writer('records/'+filename, format='mp4', mode='I', fps=int(self.fps))
        print(type(frames[0]))
        for frame in frames:
            writer.append_data(frame)
        writer.close()
        print("[INFO] Record saved as : " + str(filename) + " in records directory.")
        self.frames_to_save.clear()
        self.thread_save_record = threading.Thread(target=self.save_record, args=(), daemon=True)
    def get_storage(self):
        """Création d'une fenêtre pour visionner le stockage des enregistrements."""
        print("[INFO] Consultation des enregistrement...")
        self.ftp_window = tki.Toplevel(self.root)
        self.ftp_window.wm_protocol("WM_DELETE_WINDOW", func=self.close_ftp)
        self.ftp_window.wm_title("Consultation des enregistrements")
        try:
            self.ftp_server = FTP('_._._._', "_", "_")
            content = []
            directories = self.ftp_server.nlst()
            for directory in directories:
                for file in self.ftp_server.mlsd(directory):
                    filename, meta = file
                    if meta.get('type') == 'file':
                        size = meta.get('size')
                        last_modified = datetime.timedelta(hours=2) + datetime.datetime.strptime(meta.get("modify"), "%Y%m%d%H%M%S")
                        file_datas = str(directory) + "|" + str(filename) + "|" + str(size) + "|" + str(last_modified)
                        content.append(file_datas)

            if len(content) > 0:
                container = tki.Frame(self.ftp_window)
                canvas = tki.Canvas(container)
                scrollbar = tki.Scrollbar(container, orient="vertical", command=canvas.yview)
                scrollable_frame = tki.Frame(canvas)

                tki.Label(self.ftp_window, text=str(len(content)) + "file(s) found :").grid(sticky="N", row=1, column=1)
                tki.Label(self.ftp_window, text="Filename").grid(sticky="N", row=2, column=1)
                tki.Label(self.ftp_window, text="Taille").grid(sticky="N", row=2, column=2)
                tki.Label(self.ftp_window, text="Date").grid(sticky="N", row=2, column=3)
                for file in content:
                    file_infos = file.split("|")
                    tki.Label(self.ftp_window, text=file_infos[1]).grid(sticky="W", row=content.index(file) + 3, column=1, padx=20, pady=20)
                    tki.Label(self.ftp_window, text=file_infos[2]).grid(sticky="W", row=content.index(file) + 3, column=2, padx=20, pady=20)
                    tki.Label(self.ftp_window, text=file_infos[3]).grid(sticky="W", row=content.index(file) + 3, column=3, padx=20, pady=20)
                    tki.Button(self.ftp_window, text="\/", command=lambda file=str(file_infos[0])+'/'+str(file_infos[1]): self.download_file(file))\
                        .grid(row=content.index(file) + 3, column=4, padx=20, pady=20)
            else:
                print("No record")
        except Exception as ftp_err:
            print("FTP ERROR : " + str(ftp_err))
        #Afficher la fenêtre en continue
        self.ftp_window.mainloop()
    def download_file(self, file):
        """Telecharge le fichier sélectionné."""
        directories = ["./download/", "./download/captures/", "./download/records/"]
        created_directories = []
        for directory in directories:
            if not os.path.isdir(directory):
                try:
                    os.mkdir(directory)
                    created_directories.append(directory)
                except OSError as os_exception:
                    print("[ERROR] OS error detected : " + str(os_exception))
        if len(created_directories) > 0:
            print("[INFO] Created " + str(created_directories))
        try:
            self.ftp_server.retrbinary("RETR " + str(file), open("download/" + str(file), 'wb').write)
        except Exception as dl_err:
            print("[ERROR] Download failed : " + str(dl_err))
        else:
            print("[INFO] << " + str(file) + " >> successfully downloaded...")
    def close_ftp(self):
        """Arrête la connexion FTP et ferme la fenêtre de consultation."""
        print("[INFO] Fenêtre de consultation des enregistrements fermée")
        if not self.ftp_server is None:
            self.ftp_server = None
        self.ftp_window.destroy()
        self.thread_ftp = threading.Thread(target=self.get_storage, args=(), daemon=True)
def main():
    """ Fonction principale : Création et démarrage de l'interface client. """
    print("Camera Monitor [v3.3]")
    print("(c) 2021 by 23")
    app = CameraMonitorApp()
    app.thread.start()
    app.root.mainloop()
    del app

if __name__ == '__main__':
    main()
