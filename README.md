I created this webserver as I wanted to be able to access my dwarf3 smart telescope from a webbrowser in order to use it as a birdcam.

The webserver was created in python so you can run it on any system (Linux, Windows, raspberry pi linux) that runs the python3 interpreter. 

Beware: I created the webserver entirely using vibe-coding, so use at your own risk. Do not run it in  public networks / the internet as the webserver does not contain any security features.

Start it with
  python3 dwarf3_standalone_webserver.py TELESCOPE_IP
  
with TELECOPE_IP being the IP_Adress of your dwarf3. The webserver then will spawn on port TCP:5000, 
so by browsing to http://127.0.0.1:5000 (or whatever your PC's IP on the network is) you will reach the webserver.

Enjoy!
