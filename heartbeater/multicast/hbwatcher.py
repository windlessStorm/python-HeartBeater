#!/usr/bin/python3
# -*- encoding: utf-8 -*-
# vim: se ts=4 et syn=python:

# heartbeater/multicast/hbwatcher.py
#
#     Copyright (C) 2016 Giacomo Montagner <giacomo@entirelyunlike.net>
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#   CHANGELOG:
#
#       2016-09-19T15:02:20+02:00
#           First release.
#

import threading
import socket
import struct
import sys
import time
import random
import heartbeater.multicast.event
from heartbeater.logging import debug






class HBWatcher(threading.Thread):

    def __init__(self, softwareID, multicast_group, udp_port, interface_ip, status, timeout,
            become_master_callback,
            become_slave_callback,
            start_electing_callback,
            ):
        threading.Thread.__init__(self)
        # self.threadID = threadID
        # self.name = name
        # self.counter = counter

        self.keep_going = True

        self.softwareID = softwareID
        self.multicast_group = multicast_group
        self.udp_port = udp_port
        self.interface_ip = interface_ip
        self.status = status
        self.timeout = timeout
        self.become_master_callback = become_master_callback
        self.become_slave_callback = become_slave_callback
        self.start_electing_callback = start_electing_callback
        self.packet_destination = (multicast_group, udp_port)
        self.event_generator = heartbeater.multicast.event.EventGenerator(softwareID, status, interface_ip)

        random.seed()


    def _init_socket(self):
        # Create the datagram socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Set the reuse address flag on the socket
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind on the correct interface
        sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                socket.inet_aton(self.multicast_group) + socket.inet_aton(self.interface_ip)
                )

        # Set multicast loopback option to 1 so that we will receive our own
        # multicast packets - receiver will need to know if we're multicasting
        sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_LOOP, 1)

        # Bind
        sock.bind( (self.multicast_group, self.udp_port) )

        # Set read timeout to avoid hanging there forever
        t = self.timeout / 500      # Double timeout: timeout(in seconds) / 1000 * 2
        debug('Timeout: '+str(t))
        sock.settimeout(t)

        return sock


    def run(self):
        sock = self._init_socket()

        debug('Starting watcher')

        while (self.keep_going):
            debug('Watcher LOOP')
	    time.sleep(1)

            try:
                data, address = sock.recvfrom(4096)

                incoming_event = self.event_generator.parse_json(data)

                if (incoming_event.is_local_to(self.softwareID, self.interface_ip)):
                    # The incoming event was generated by us - we're MASTER
                    debug('I see myself')
                    if self.status.is_electing():
                        # We were electing, we elect ourselves:
                        debug('I elect MYSELF!')
                        self.status.become_master()
                        self.become_master_callback()

                else:
                    if (self.status.is_master() and incoming_event.is_master()):
                        # Master conflict! Become slave, random wait and then retry
                        debug('Master conflict!')
                        self.status.become_slave()
                        r = random.random()
                        time.sleep(r)

                    elif (self.status.is_electing()):
                        # We were electing, someone spoke before us
                        debug('Someone (not me) claimed the throne, election is over')
                        self.status.become_slave()

            except socket.timeout:
                if (self.status.is_master()):
                    # I am master but I see no one (not even myself) - still, I have nothing to do
                    debug('I see no one, not even myself. I am MASTER and I will stay so')
                    pass
                elif (self.status.is_electing()):
                    # We're trying to elect a master, but we still see no one, this should not be
                    # happening. Still, I elect myself (I see no one else)
                    debug("We're electing and I should see myself. I don't. I'll become master anyway.")
                    self.status.become_master()
                    self.become_slave_callback()
                else:
                    # We're slave and no one is speaking, election time
                    debug('I am SLAVE and I see no one, time to elect!')
                    self.status.start_electing()
                    self.start_electing_callback()



    def stop(self):
        self.keep_going = False
