#!/usr/bin/env python3
# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
Test fork choice rule between parallel justification forks

The following checks are performed:
1. node re-orgs to the longer justified parallel fork
2. node re-orgs to the previous fork that became longer justified one
3. node doesn't re-org before finalization
"""

from test_framework.test_framework import UnitETestFramework
from test_framework.mininode import (
    P2PInterface,
    network_thread_start,
    msg_witness_block,
)

from test_framework.util import (
    connect_nodes,
    disconnect_nodes,
    assert_equal,
    sync_blocks,
    wait_until,
)
from test_framework.messages import (
    CTransaction,
    CBlock,
    FromHex,
)
from test_framework.regtest_mnemonics import regtest_mnemonics


class BaseNode(P2PInterface):
    def __init__(self):
        super().__init__()
        self.rejects = []

    def on_reject(self, msg):
        self.rejects.append(msg)

    def has_reject(self, err, block):
        for r in self.rejects:
            if r.reason == err and r.data == block:
                return True
        return False


class ForkChoiceParallelJustificationsTest(UnitETestFramework):
    def set_test_params(self):
        self.num_nodes = 5
        self.setup_clean_chain = True

        esperanza_config = '-esperanzaconfig={"epochLength":5}'
        self.extra_args = [
            ['-proposing=0', esperanza_config],
            ['-proposing=0', esperanza_config],
            ['-proposing=0', esperanza_config],
            ['-proposing=0', esperanza_config, '-validating=1'],
            ['-proposing=0', esperanza_config, '-validating=1'],
        ]

    def setup_network(self):
        self.setup_nodes()

    def run_test(self):
        def create_justification(fork, finalizer, after_blocks):
            fork.generatetoaddress(after_blocks - 1, fork.getnewaddress())
            self.wait_for_vote_and_disconnect(finalizer=finalizer, node=fork)
            fork.generatetoaddress(1, fork.getnewaddress())
            assert_equal(len(fork.getrawmempool()), 0)

        def sync_node_to_fork(node, fork):
            connect_nodes(node, fork.index)
            block_hash = fork.getblockhash(fork.getblockcount())
            node.waitforblock(block_hash, 5000)
            assert_equal(node.getblockhash(node.getblockcount()), block_hash)
            disconnect_nodes(node, fork.index)

        def wait_for_reject(p2p, err, block):
            wait_until(lambda: p2p.has_reject(err, block), timeout=5)

        # Two validators (but actually having the same key) produce parallel justifications
        # node must always follow the longest justified fork
        # finalizer1 -> fork1
        #             /
        #           node
        #             \
        # finalizer2 -> fork2
        node = self.nodes[0]
        fork1 = self.nodes[1]
        fork2 = self.nodes[2]
        finalizer1 = self.nodes[3]
        finalizer2 = self.nodes[4]

        node.importmasterkey(regtest_mnemonics[0]['mnemonics'])
        finalizer1.importmasterkey(regtest_mnemonics[1]['mnemonics'])
        finalizer2.importmasterkey(regtest_mnemonics[1]['mnemonics'])

        # create network topology
        connect_nodes(node, fork1.index)
        connect_nodes(node, fork2.index)
        connect_nodes(finalizer1, fork1.index)
        connect_nodes(finalizer2, fork2.index)

        # leave IBD
        node.generatetoaddress(2, node.getnewaddress())
        sync_blocks([node, fork1, fork2, finalizer1, finalizer2])

        payto = finalizer1.getnewaddress('', 'legacy')
        txid1 = finalizer1.deposit(payto, 10000)
        finalizer2.setaccount(payto, '')
        txid2 = finalizer2.deposit(payto, 10000)
        if txid1 != txid2:  # improve log message
            tx1 = FromHex(CTransaction(), finalizer1.getrawtransaction(txid1))
            tx2 = FromHex(CTransaction(), finalizer2.getrawtransaction(txid2))
            print(tx1)
            print(tx2)
            assert_equal(txid1, txid2)

        self.wait_for_transaction(txid1, timeout=150)

        node.generatetoaddress(1, node.getnewaddress())
        sync_blocks([node, fork1, fork2])

        disconnect_nodes(node, fork1.index)
        disconnect_nodes(node, fork2.index)
        disconnect_nodes(finalizer1, fork1.index)
        disconnect_nodes(finalizer2, fork2.index)

        # create common 4 epochs to leave instant finalization
        #                        fork1
        # F    F    F    J      /
        # e0 - e1 - e2 - e3 - e4 node
        #                       \
        #                        fork2
        node.generatetoaddress(21, node.getnewaddress())
        assert_equal(node.getblockcount(), 24)
        assert_equal(node.getfinalizationstate()['currentEpoch'], 4)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 2)
        assert_equal(node.getfinalizationstate()['lastFinalizedEpoch'], 2)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 3)
        assert_equal(node.getfinalizationstate()['validators'], 1)

        connect_nodes(node, fork1.index)
        connect_nodes(node, fork2.index)
        sync_blocks([node, fork1, fork2])
        disconnect_nodes(node, fork1.index)
        disconnect_nodes(node, fork2.index)

        # create fist justified epoch on fork1
        # node must follow this fork
        #
        #                        - e5 fork1, node
        # F    F    F    J    * /
        # e0 - e1 - e2 - e3 - e4
        #                       \
        #                        fork2
        # e3 is finalized for fork1
        # e4 is justified for fork1
        create_justification(fork=fork1, finalizer=finalizer1, after_blocks=2)
        assert_equal(fork1.getblockcount(), 26)
        assert_equal(fork1.getfinalizationstate()['currentEpoch'], 5)
        assert_equal(fork1.getfinalizationstate()['currentDynasty'], 3)
        assert_equal(fork1.getfinalizationstate()['lastJustifiedEpoch'], 4)

        sync_node_to_fork(node, fork1)

        assert_equal(node.getfinalizationstate()['currentEpoch'], 5)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 3)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 4)

        self.log.info('node successfully switched to the justified fork')

        # create longer justified epoch on fork2
        # node must switch ("zig") to this fork
        #
        #                        - e5 fork1
        # F    F    F    J    * /
        # e0 - e1 - e2 - e3 - e4
        #                       \       J
        #                        - e5 - e6 - e7 fork2, node
        # e3 is finalized for fork1
        # e4 is justified for fork1
        create_justification(fork=fork2, finalizer=finalizer2, after_blocks=12)
        assert_equal(fork2.getblockcount(), 36)
        assert_equal(fork2.getfinalizationstate()['currentEpoch'], 7)
        assert_equal(fork2.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(fork2.getfinalizationstate()['lastJustifiedEpoch'], 6)

        sync_node_to_fork(node, fork2)

        assert_equal(node.getfinalizationstate()['currentEpoch'], 7)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 6)

        self.log.info('node successfully switched to the longest justified fork')

        # create longer justified epoch on the previous fork1
        # node must switch ("zag") to this fork
        #                                    J
        #                        - e5 - e6 - e7 - e8 fork1, node
        # F    F    F    J    * /
        # e0 - e1 - e2 - e3 - e4
        #                       \       J
        #                        - e5 - e6 - e7 fork2
        # e3 is finalized for fork1
        # e4 is justified for fork1
        create_justification(fork=fork1, finalizer=finalizer1, after_blocks=16)
        assert_equal(fork1.getblockcount(), 42)
        assert_equal(fork1.getfinalizationstate()['currentEpoch'], 8)
        assert_equal(fork1.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(fork1.getfinalizationstate()['lastJustifiedEpoch'], 7)

        sync_node_to_fork(node, fork1)

        assert_equal(node.getfinalizationstate()['currentEpoch'], 8)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 7)

        self.log.info('node successfully switched back to the longest justified fork')

        # test that re-org before finalization is not possible
        # node's view:
        #                                    J              J
        #                        - e5 - e6 - e7 - e8 - e9 - e10 - e11 (tip)
        # F    F    F    F    J /
        # e0 - e1 - e2 - e3 - e4
        #                       \       J
        #                        - e5 - e6 - e7
        known_fork1_height = fork1.getblockcount()
        assert_equal(node.getblockcount(), known_fork1_height)

        known_fork1_hash = fork1.getblockhash(known_fork1_height)
        assert_equal(node.getblockhash(known_fork1_height), known_fork1_hash)
        create_justification(fork=fork1, finalizer=finalizer1, after_blocks=14)

        assert_equal(fork1.getblockcount(), 56)
        assert_equal(fork1.getfinalizationstate()['currentEpoch'], 11)
        assert_equal(fork1.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(fork1.getfinalizationstate()['lastJustifiedEpoch'], 10)
        assert_equal(fork1.getfinalizationstate()['lastFinalizedEpoch'], 3)

        attacker = node.add_p2p_connection(BaseNode())
        network_thread_start()
        attacker.wait_for_verack()

        # send blocks without the last one that has a justified vote
        node_blocks = node.getblockcount()
        for h in range(known_fork1_height + 1, fork1.getblockcount()):
            block_hash = fork1.getblockhash(h)
            block = FromHex(CBlock(), fork1.getblock(block_hash, 0))
            attacker.send_message(msg_witness_block(block))
            node_blocks += 1
            wait_until(lambda: node.getblockcount() == node_blocks, timeout=15)

        assert_equal(node.getblockcount(), 55)
        assert_equal(node.getfinalizationstate()['currentEpoch'], 11)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 7)
        assert_equal(node.getfinalizationstate()['lastFinalizedEpoch'], 3)

        # create finalization
        # node's view:
        #                                    J              J
        #                        - e5 - e6 - e7 - e8 - e9 - e10 - e11
        # F    F    F    F    J /
        # e0 - e1 - e2 - e3 - e4
        #                       \       J         F    J
        #                        - e5 - e6 - e7 - e8 - e9 - e10 - e11 (tip)
        create_justification(fork=fork2, finalizer=finalizer2, after_blocks=11)
        assert_equal(fork2.getblockcount(), 47)
        assert_equal(fork2.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(fork2.getfinalizationstate()['currentEpoch'], 9)
        assert_equal(fork2.getfinalizationstate()['lastJustifiedEpoch'], 8)
        assert_equal(fork2.getfinalizationstate()['lastFinalizedEpoch'], 3)

        create_justification(fork=fork2, finalizer=finalizer2, after_blocks=6)
        assert_equal(fork2.getblockcount(), 53)
        assert_equal(fork2.getfinalizationstate()['currentDynasty'], 4)
        assert_equal(fork2.getfinalizationstate()['currentEpoch'], 10)
        assert_equal(fork2.getfinalizationstate()['lastJustifiedEpoch'], 9)
        assert_equal(fork2.getfinalizationstate()['lastFinalizedEpoch'], 8)

        fork2.generatetoaddress(3, fork2.getnewaddress())
        assert_equal(fork2.getblockcount(), 56)
        assert_equal(fork2.getfinalizationstate()['currentDynasty'], 5)
        assert_equal(fork2.getfinalizationstate()['currentEpoch'], 11)
        assert_equal(fork2.getfinalizationstate()['lastJustifiedEpoch'], 9)
        assert_equal(fork2.getfinalizationstate()['lastFinalizedEpoch'], 8)

        tip = fork2.getblockhash(56)
        sync_node_to_fork(node, fork2)

        assert_equal(node.getblockcount(), 56)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 5)
        assert_equal(node.getfinalizationstate()['currentEpoch'], 11)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 9)
        assert_equal(node.getfinalizationstate()['lastFinalizedEpoch'], 8)

        # send block with surrounded vote that justifies longer fork
        # node's view:
        #                          J         J              J
        #                        - e5 - e6 - e7 - e8 - e9 - e10 - e11
        #                       /
        # e0 - e1 - e2 - e3 - e4
        #                       \       J         F    J
        #                        - e5 - e6 - e7 - e8 - e9 - e10 - e11 (must stay here)

        block_hash = fork1.getblockhash(fork1.getblockcount())
        block = FromHex(CBlock(), fork1.getblock(block_hash, 0))
        block.calc_sha256()
        attacker.send_message(msg_witness_block(block))

        # node should't re-org to malicious fork
        wait_for_reject(attacker, b'bad-fork-dynasty', block.sha256)
        assert_equal(node.getblockcount(), 56)
        assert_equal(node.getblockhash(56), tip)
        assert_equal(node.getfinalizationstate()['currentEpoch'], 11)
        assert_equal(node.getfinalizationstate()['currentDynasty'], 5)
        assert_equal(node.getfinalizationstate()['lastJustifiedEpoch'], 9)
        assert_equal(node.getfinalizationstate()['lastFinalizedEpoch'], 8)

        self.log.info('node did not re-org before finalization')


if __name__ == '__main__':
    ForkChoiceParallelJustificationsTest().main()