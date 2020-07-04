#!/usr/bin/python3
'''
Copyright (c) 2017 - 2018 Blake <0x431999@StudioTeabag.com>

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

## "IWUP" v1.2 by Blake @ StudioTeaBag - License: ISC ##

Dependencies:
-------------
GObject library should already be installed because of D-Bus itself.
    - Likely 'pygobject3' or 'python3-gobject' in your package manager.

Python D-Bus
    - pip3 install pydbus

Tested Distributions:
------------------------
    - Fedora 26, 27
    - openSUSE Leap 42.3, Tumbleweed

Why does this exist:
--------------------
Mostly as a fun experiment to learn more about D-Bus and Python.

It can also be argued that a cronjob + bash script that polls and reloads does
not make for an efficient battery use case.

ISC license because of that 0.0001% chance it breaks hardware or that it causes
someone to have a very very bad day. Hope it serves you well.

Too Long, Didn't Read:
----------------------
"Is Wireless UP" (IWUP) is a Python script that monitors WPA Supplicant and will
then proceed to reload a specified Kernel module. The reason to go through this 
effort is that the Venue 8 and 11 stock Dell Wireless module disconnects after 
38 - 45 minutes and the interface will refuse to reconnect unless the Kernel 
module itself is removed and re-inserted.

WPA Supplicant notices this almost instantly and a connection can be restored in
as little as ~6 seconds. Network Manager takes a minimum ~21 seconds. Hence why
our primary source of information is WPA Supplicant.

Uses about ~10MB of system memory when running. Alot really for what it does...

Hat Tips:
---------
    https://github.com/LEW21/pydbus
    https://lazka.github.io/pgi-docs/Gio-2.0/classes/DBusConnection.html

    https://gist.github.com/bossjones/60410574b11c75439965
    https://github.com/tarruda/wpas/blob/master/wpas.py

Reading:
--------
    %: "Reason Codes" - IEEE Std 802.11-2012 Section 8.4.1.7
    https://supportforums.cisco.com/document/141136/80211-association-status-80211-deauth-reason-codes

    %: Network Manager Responses
    https://developer.gnome.org/NetworkManager/stable/nm-dbus-types.html

Changelog:
----------
    - v1.0 Unreleased (July 2017)
           Initial Version
    - v1.1 Release Candidate (August 2017)
           Clean ups and Fixes
    - v1.2 Official Release (January 2018/01/01)
           Import Checks
           Command line arguments for interface / module switching
           Exit Handler

To-Do List:
-----------
    - Allow startup without being connected to an Access Point.
    - Hooking into the desktop notifier for the current user session.
    - Crafting a basic systemd unit for cruise control magic.
    - Allow a comma seperated list of kernel modules so an entire stack can be reloaded.

Known Quirks:
-------------
    - Manual disconnect may (in worst case) trigger module reload action.

'''

''' The Basics, stock standard Python 3 '''
import os, sys, signal
import subprocess
import datetime
import time

import argparse
parser = argparse.ArgumentParser()

parser.add_argument("-i", "--interface", help="Network Interface to monitor.")
parser.add_argument("-m", "--module", help="Kernel Module to remove / probe.")

args = parser.parse_args()

''' External Dependencies '''
try:
    from gi.repository import GLib
except:
    print("[!] You do not appear to have the 'GLib' module available.")
    print("    GLib is part of the GObject Introspection library.")
    print("    ")
    print("    Search for 'pygobject3' or 'python3-gobject' in your")
    print("    system's package manager.")
    sys.exit(0)

try:
    from pydbus import SystemBus
except:
    print("[!] You do not appear to have the 'pydbus' module installed.")
    print("    'pip3 install pydbus' should resolve that for you.")
    sys.exit(0)

''' The Essential Mix '''
wpa_bot_version = "1.2"

loop = GLib.MainLoop()
bus = SystemBus()

if args.interface == None:
    wifi_device = "wlan0"
else:
    wifi_device = args.interface

if args.module == None:
    wifi_module = "ath6kl_sdio"
else:
    wifi_module = args.module

def signal_handler(signal, frame):
    print("\nProgram exiting gracefully")
    sys.exit(0)

def timeStamp():
    current_time = datetime.datetime.now()
    stamp = "[-] " + "{:%H:%M:%S}".format(current_time)
    return stamp

'''
I did not want to import an extra dependency for what is basically running 2 
commands and getting the result.

The reason for having a check in there is that sometimes the module will fail 
to insert if the hardware is in a FUBAR state. Only way to fix that is reboot.
'''

def kmod():
    print(timeStamp())
    
    remove_module = subprocess.Popen(['rmmod',wifi_module],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    remove_status = remove_module.wait()

    insert_module = subprocess.Popen(['modprobe',wifi_module],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    insert_status = insert_module.wait()

    if remove_status is 1:
        remove_module_stderr = remove_module.stderr.read()
        print("[!] " + remove_module_stderr.decode('ascii'))
    else:
        print("[#] modprobe: Phase 1, Removed module '" + wifi_module + "'.")

    if insert_status is 1:
        insert_module_stderr = insert_module.stderr.read()
        print("[!] " + insert_module_stderr.decode('ascii'))
        print("[^] Bailing out, something went horribly wrong...")
        sys.exit(0)
    else:
        print("[#] modprobe: Phase 1, Adding module '" + wifi_module + "'.")
        kmod_check()

def kmod_check():
    print ("[#] modprobe: Phase 2, Confirming... ")
    check_module = subprocess.Popen(['lsmod','|','grep',wifi_module],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    check_status = check_module.wait()

    if check_status is 0:
        print("[!] modprobe: There was an attempt to load the module, yet it failed.")
    else:
        print("[@] modprobe: Procedure complete.")
        print(timeStamp())

'''
Each time WPA Supplicant starts a new connection session the internal interface
path we want to listen on changes. So we politely ask and subscribe.
'''

def dbus():
    print("[#] Updating D-Bus Paths.")
    
    print(timeStamp())

    ''' Define WPA Supplicant Bus '''
    wpa_supplicant = "fi.w1.wpa_supplicant1"
    wpa = bus.get(wpa_supplicant)

    ''' Get the Proxy End Point for our Interface '''
    ''' If the interface cannot be found inform the user and exit '''
    try:
        wpa_iface = wpa.GetInterface(wifi_device)
    except:
        sys.exit("[!] Interface '" + wifi_device + "' is not registered with the WPA supplicant.")

    iface = bus.get(wpa_supplicant, wpa_iface);

    ''' Inform the User '''
    print("[#] Path : " + wpa_iface)
    print("[#] Net  : " + iface.CurrentNetwork)

    ''' Knowing the Proxy we can inquire things. '''
    current = bus.get(wpa_supplicant, iface.CurrentNetwork);
    print("[#] SSID : " + current.Properties["ssid"])
    
    '''
    If a signal_subscribe returns 0 it means it didn't do a thing.
    
    For some reason, have mixed feelings about this, but it works.
    Would expect interface parameter to be "fi.w1.foo.bar" rather then "org.freedesktop.*"
    But I am new to pydbus etc.
    '''
    
    ''' Subscribe '''
    wpa_propchan = bus.con.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", wpa_iface, None, 0, wpa_changed)

    if wpa_propchan > 0:
        print ("[#] Subscribed to 'PropertiesChanged' on WPA Supplicant.")

'''
We like to know when Network Manager has caught up with us.
'''

def nmBus():
    netman_sup = bus.con.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", "/org/freedesktop/NetworkManager", None, 0, nm_changed)
    if netman_sup > 0:
        print ("[#] Subscribed to 'PropertiesChanged' on NetworkManager.")

def nm_changed(*args):
    for i, gra in enumerate(args[5]):
        if i == 1:
        
            for k, v in gra.items():
                if k == "Connectivity":
                    if v > 1:
                        print(timeStamp())
                        print("[#] NM Connectivity State: " + str(v))
                        dbus()

'''
When the Wireless card drops WPA Supplicant will report a De-Authentication 
event which correlates to code 3. When this happens we reload the Kernel
Modules and hope for the best.
'''

def wpa_changed(*args):
    for i, gra in enumerate(args[5]):
        if i == 1:
        
            for k, v in gra.items():
                if v == "interface_disabled":
                    print("[!] - Interface Disabled... ")

                if k == "DisconnectReason":
                    print(timeStamp())

                    print("[!] - Disconnect Detected -")
                    if v < 3:
                        print("[#] Normal, No action required.")
                    else:
                        print("[!] DeAuth, Reloading kmods.")
                        kmod()

'''
1. Say Hello to Network Manager
2. Say Hello to WPA Supplicant Again.
3. Keep running.
'''

def main():
    if not os.geteuid()==0:
        sys.exit("[!] Helps to be Root my friend.")

    print("    WPA D-Bus Bot v" + wpa_bot_version)

    if args.interface == None:
        print("[%] No interface specified, assuming " + wifi_device + ".")

    if args.module == None:
        print("[%] No module specified, assuming " + wifi_module + ".")

    nmBus()
    dbus()
    loop.run()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\n[*] Shutting Down.")


