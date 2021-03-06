// Copyright (c) 2018-2019 The Unit-e developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef UNITE_PROPOSER_PROPOSER_H
#define UNITE_PROPOSER_PROPOSER_H

#include <dependency.h>

#include <memory>

struct Settings;

namespace blockchain {
class Behavior;
}

namespace staking {
class ActiveChain;
class Network;
class TransactionPicker;
}  // namespace staking

namespace proposer {

class BlockBuilder;
class Logic;
class MultiWallet;

class Proposer {

 public:
  virtual void Wake() = 0;

  virtual void Start() = 0;

  virtual void Stop() = 0;

  virtual bool IsStarted() = 0;

  virtual ~Proposer() = default;

  static std::unique_ptr<Proposer> New(Dependency<Settings>,
                                       Dependency<blockchain::Behavior>,
                                       Dependency<MultiWallet>,
                                       Dependency<staking::Network>,
                                       Dependency<staking::ActiveChain>,
                                       Dependency<staking::TransactionPicker>,
                                       Dependency<BlockBuilder>,
                                       Dependency<Logic>);
};

}  // namespace proposer

#endif  // UNITE_PROPOSER_PROPOSER_H
