#!/bin/bash
# PATH : /home/pi/server-v1/server.sh
SOCKET_PORT=8001
printf "Camera network handler [v1.0]\n(c) 2021 by 23\n"
while :
do
	#Tableau des caméra disponibles dans le réseau
	CAMERA=($(nmap -p 81 192.168.10.10-20 | grep "Nmap scan report for" | cut -f 5 -d ' '))
	#Tableau des connexions en cours entre le serveur et les caméras du réseau
	CONNECTIONS=($(netstat -e | grep 192.168.10. | cut -d: -f2 | cut -f 5 -d ' '))
	#Tableau des ports en écoute
	USED_PORT=($(lsof -i | grep LISTEN | cut -f 22 -d ' ' | cut -d: -f2))
	#Passer les caméras disponibles en revue, une par une
	for ip in ${CAMERA[*]}; do
			#Verifier si une connexion existe entre le serveur et cette caméra
			if [[ ! " ${CONNECTIONS[*]} " =~ " $ip " ]]; then
				echo "No stream for $ip, start it"
				#Si le port 8001 est déjà en écoute, ...
				while [[ " ${USED_PORT[*]} " =~ " $SOCKET_PORT " ]]; do
						echo "Port $SOCKET_PORT already used"
						#...essayer le port suivant
						((SOCKET_PORT=SOCKET_PORT+1))
				done
				#Démarrer le programme de diffusion et de surveillance pour cette caméra
				echo "Start program for $ip:81 on port $SOCKET_PORT"
				python3.7 stream_and_surveillance.py --url http://$ip:81 --port $SOCKET_PORT &
				sleep 2
				SOCKET_PORT=8001
			fi
	done
	CONNECTIONS=($(netstat -e | grep 192.168.10. | cut -d: -f2 | cut -f 5 -d ' '))
done