#!/usr/bin/env python3
# Copyright (c) 2019 The Unit-e developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
FeatureFinalizerTest tests the following:
1. Finalizer can vote after the restart
"""

from test_framework.test_framework import UnitETestFramework
from test_framework.util import (
    assert_equal,
    assert_finalizationstate,
    connect_nodes,
    sync_blocks,
)


def generate_block(node):
    node.generatetoaddress(1, node.getnewaddress('', 'bech32'))


class FeatureFinalizerTest(UnitETestFramework):
    def set_test_params(self):
        self.num_nodes = 2
        self.extra_args = [
            ['-esperanzaconfig={"epochLength": 5, "minDepositSize": 1500}'],
            ['-esperanzaconfig={"epochLength": 5, "minDepositSize": 1500}', '-validating=1'],
        ]
        self.setup_clean_chain = True

    def setup_network(self):
        self.setup_nodes()
        p, v = self.nodes
        connect_nodes(p, v.index)

    def run_test(self):
        # Check finalizer can vote after restart
        p, v = self.nodes
        self.setup_stake_coins(p, v)
        self.generate_sync(p)

        self.log.info("Setup deposit")
        v.new_address = v.getnewaddress("", "legacy")
        tx = v.deposit(v.new_address, 1500)
        self.wait_for_transaction(tx)
        p.generatetoaddress(1, p.getnewaddress('', 'bech32'))
        sync_blocks([p, v])

        self.log.info("Restart validator")
        self.restart_node(v.index)

        self.log.info("Leave insta justification")
        for _ in range(24):
            generate_block(p)
        assert_equal(p.getblockcount(), 26)
        assert_finalizationstate(p, {"currentEpoch": 6,
                                     "lastJustifiedEpoch": 4,
                                     "lastFinalizedEpoch": 3,
                                     "validators": 1})

        self.log.info("Check finalizer votes after restart")
        self.wait_for_vote_and_disconnect(finalizer=v, node=p)
        generate_block(p)

        assert_equal(p.getblockcount(), 27)
        assert_finalizationstate(p, {"currentEpoch": 6,
                                     "lastJustifiedEpoch": 5,
                                     "lastFinalizedEpoch": 4,
                                     "validators": 1})


if __name__ == '__main__':
    FeatureFinalizerTest().main()
