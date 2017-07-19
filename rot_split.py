#!/usr/bin/python

# rot_split_V2.py: allow Nostradamus our Lord to control GH RT-21 Az-El rotor controller
# Do not manually run this script. Run start_rotor.sh.
# Written for UCLA's ELFIN mission <elfin.igpp.ucla.edu>
# By Micah Cliffe (KK6SLK) <micah.cliffe@ucla.edu>
# Edited by Alexander Gonzalez (KM6ISP) <gonzalezalexander1997@gmail.com>

# Interface with GPredict removed. Azimuth and elevation from custom tracking script (nostradamus.py) that uses PyEphem.

import socket
import errno
import time
import nostradamus
import signal
import os.path
import telnetlib
from math import *

# Constants
HOST        = 'localhost'
LOCALHOST   = '127.0.0.1'
azPORT      = 4535
elPORT      = 4537
GQRXPORT    = 7356
REC_SZ      = 1024
RUN_FOREVER = True
LIGHT_SPEED = 299792 #km/s


REQUEST_TIMEOUT = 10 #seconds

AZ_PARK = "130"
EL_PARK = "90"

###############################################################################
class client_socket:
    def __init__(self, sock=None):
        self.maxRetry  = 5
        self.retryTime = 1
        if sock is None:
            self.sock = socket.socket()
        else:
            self.sock = sock

    def connect(self, host, port):
        for attempt in range(self.maxRetry):
            try:
                self.sock.connect((host,port))
            except EnvironmentError as e:
                if e.errno == errno.ECONNREFUSED:
                    time.sleep(self.retryTime)
                else:
                    raise
            else:
                break
        else:
            raise RuntimeError("Maximum number of unsuccessful attempts reached")

    def send(self, msg):
        self.sock.send(msg)

    def get_response(self):
        return self.sock.recv(REC_SZ)

    def __del__(self):
        self.sock.close()
##############################################################################
class AlarmException(Exception):
    pass

def alarmHandler(signum, frame):
    raise AlarmException

def new_command_request(prompt = '\nEnter "S" to switch satellites, "C" to change command, do nothing to continue: ', timeout = REQUEST_TIMEOUT):
    #non-blocking raw input (issues with blocking interruption)
    signal.signal(signal.SIGALRM, alarmHandler)
    signal.alarm(timeout)
    global user_choice
    user_choice = ''
    try:
        user_choice = raw_input(prompt)
        signal.alarm(0)
        print  "\nInput successful. \n"
        return user_choice
    except AlarmException:
        print "\nNo changes made.\n"
    signal.signal(signal.SIGALRM, signal.SIG_IGN)
    return user_choice

def new_command_execute(user_input):
    user_input = user_input.upper()
    if user_input == 'S':
        select_satellite()
        print "Executing new command..."
    elif user_input == 'C':
        command_request()
        print "Executing new command..."
    elif user_input == '':
        pass
    else:
        print "Unknown input. No changes made."
        pass

###############################################################################
class RadioControl():
    """Basic rigctl client implementation."""

    def __init__(self, hostname=LOCALHOST, port=GQRXPORT):
        self.hostname = hostname
        self.port = port

    def _request(self, request):
        con = telnetlib.Telnet(self.hostname, self.port)
        con.write(('%s\n' % request).encode('ascii'))
        response = con.read_some().decode('ascii').strip()
        con.write('c\n'.encode('ascii'))
        return response

    def set_frequency(self, frequency):
        return self._request('F %s' % frequency)

    def get_frequency(self):
        return self._request('f')

    def set_mode(self, mode):
        return self._request('M %s' % mode)

    def get_mode(self):
        return self._request('m')

    def get_level(self):
        return self._request('l')
###############################################################################
def main():

#Creates sockets for az and el of rotor controller
    global az
    global el
    try:
        az       = client_socket()
        el       = client_socket()
    except Exception as e:
        print "Could not make sockets. Exiting."
        print e
        sys.exit(1)
    az.connect(HOST, azPORT)
    el.connect(HOST, elPORT)
    print "Connected to rotctld instances."
#Initialize radio controller
    global r
    r = RadioControl()
#Initialize nostradamus
    global n
    n = nostradamus.Predictor()

#Update TLEs before starting
    n.updateTLEs()

#Choose satellite to track and command to send to rotor controller
    select_satellite()
    command_request()

#Prints current station and satellite. Optional to set station through nostradamus function
    print "\nSTATION: " + n.getStation()
    print "SATELLITES: " + str(n.getSatellites())

#TODO: auto switch between csun and firebird. how i do dat???
#TODO: get pass time in PST


#Loop 1: IN_RANGE -> starts tracking
#Loop 2: not IN_RANGE -> will print pos and keep checking for LOS.
#When LOS established, loop 1 runs. When LOS lost, loop 2 runs.
#RUN_FOREVER keeps the script switching between loop 1 and 2

    while RUN_FOREVER:

        print "\n______________Listening to Nostradamus______________"
        print "\nSTATION: " + n.getStation()
        print "SATELLITES: " + str(n.getSatellites()) + "\n"
#Compute pos and put into rotorcmd
        start_tracker(satellite)

#Doppler shifted frequency tracked and set in GQRX via port
        shift = doppler_shift(frequency)
        doppler_corrected_freq = int(frequency + shift)
        r.set_frequency(doppler_corrected_freq)

#Check if satellite is in LOS to determine loop entry
        check_LOS(satellite, pos)

        while IN_RANGE is False:
            check_satellite(satellite, pos, doppler_corrected_freq)
            command_execute()
            new_command_request()
            new_command_execute(user_choice)
            break

        while IN_RANGE is True:
            check_satellite(satellite, pos, doppler_corrected_freq)
            command_execute()
            new_command_request()
            new_command_execute(user_choice)
            break

        time.sleep(1) #seconds


def command_execute():
    if selection == 'q':
        print "\nSHUTTING DOWN DEATHSTAR."
        quit()
    elif selection == 'p':
        get_position(az, el)
    elif selection == 'P': # and IN_RANGE:
        valid_set = set_position(az, el, rotorcmd)
        get_position(az, el)
        '''
        if not valid_set:
            print "%s out of range. Exiting." % satellite
            break
        '''
    elif selection == 'Q':
        print "\nParking the deathstar...\n"
        set_parking(az, el, rotorcmd)
        quit()
    else:
        print "%s out of range. Tracking not engaged." % satellite

def get_position(az, el):
    print "\nRequesting superlaser position... "
    azCtrl = 'p' + ' ' + '0' + ' 0\n'
    az.send(azCtrl)
    az_response = az.get_response().splitlines()[0]
    elCtrl = 'p' + ' ' + '0' + ' 0\n'
    el.send(elCtrl)
    el_response = el.get_response().splitlines()[0]
    response = "\nAZ: " + az_response + '\n' + "EL: "+  el_response + '\n'
    print "Response: " + response

def set_position(az, el, cmd):
    print "\nAiming superlaser..."
    cmd  = cmd.split(',')
    # cmd = [P, AZIMUTH, ELEVATION]
    azCtrl = cmd[0] + ' ' + cmd[1] + ' 0\n'
    az.send(azCtrl)
    if float(cmd[2]) < 0:
        cmd[2] = '0'
    elCtrl = cmd[0] + ' ' + cmd[2] + ' 0\n'
    el.send(elCtrl)
    print "Commands sent."
    print "AZ: " + azCtrl
    print "EL: " + elCtrl
    az_resp = az.get_response()
    el_resp = el.get_response()
    print "Checking superlaser..."
    print "AZ: " + az_resp
    print "EL: " + el_resp
    if az_resp == el_resp and az_resp == "RPRT 0\n":
        pass
    else:
        print "HAMLIB ERROR."
        return 0

def set_parking(az, el, cmd):
    print "___Setting Position___ "
    print "AZ: " +  AZ_PARK + "\nEL: " + EL_PARK
    azCtrl = "P" + ' ' + AZ_PARK + ' 0\n'
    az.send(azCtrl)
    elCtrl = "P" + ' ' + EL_PARK + ' 0\n'
    el.send(elCtrl)
    az_resp = az.get_response()
    el_resp = el.get_response()
    if az_resp == el_resp and az_resp == "RPRT 0\n":
        print "Deathstar succesfully parked..."
        pass
    else:
        print("Couldnt park deathstar :( ", az_resp, el_resp)

def select_satellite():
    while True:
        global satellite
        global frequency
        satellite = raw_input("Which satellite would you like to track? ")

        valid = n.addSatellite(satellite)
        if(valid):
            if satellite == "FIREBIRD 4":
                frequency = 437219000 #Hz
            elif satellite == "CSUNSAT 1":
                frequency = 437400000 #Hz
            else:
                frequency =raw_input("Enter center frequency: ")
                frequency = int(frequency)
            break
        else:
            #check if spelling is correct or if satellite is in tle.txt
            print "Please enter valid satellite."

def command_request():
    while True:
        valid_options = ['p', 'P', 'q','Q']
        global selection
        selection = raw_input("Enter p to get current position, P to track satellite, Q to park, q to quit: ")
        if selection not in valid_options:
            print "Unknown command. Please enter a valid command."
        else:
            break

def check_satellite(sat, position, freq):
        check =  position.split(',')
        check_az = '%.2f' % float(check[0])
        check_el = '%.2f' % float(check[1])
        check_vel = '%.3f' % vel
        print "Acquiring Target: %s " % sat
        print "AZ: " + str(check_az)
        print "EL: " + str(check_el)
        print "Range Rate: %s km/s" % str(check_vel)
        print "AOS: %s (UTC)" % passinfo[0]
        print "LOS: %s (UTC)" % passinfo[4]
        #print "Rise azimuth: %s" % ('%.2f' % degrees(passinfo[1]))
        print "Frequency: %s Hz" % str(frequency)
        print "Doppler Shifted Frequency: %s Hz" % str(freq)
        print "GQRX Frequency: " + r.get_frequency() + " Hz"

def check_LOS(sat, position):
        #checks if satellite is above horizon. If below horizon, az can be set but not el
        check =  position.split(',')
        check_az = float(check[0])
        check_el = float(check[1])
        global IN_RANGE
        if check_el < 0:
            print "%s currently below horizon. EL cannot be set. \n" % sat
            IN_RANGE = False
        else:
            print "%s in LOS. Tracking can commence. \n" % sat
            IN_RANGE = True
        return IN_RANGE

def start_tracker(sat):
    global pos
    pos = n.position(sat)
    n.loadTLE(sat)
    pos = str(pos).strip('()')
    global vel
    vel = n.velocity(sat)
    global passinfo
    passinfo = n.nextpass(sat)
    global rotorcmd
    rotorcmd = selection + ' , ' + pos
    return rotorcmd

def doppler_shift(freq):
    range_rate = abs(vel)
    return (range_rate/LIGHT_SPEED) * freq



###############################################################################
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print "\nExiting.\n"
