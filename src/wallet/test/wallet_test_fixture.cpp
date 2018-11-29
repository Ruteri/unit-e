// Copyright (c) 2016-2017 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <wallet/test/wallet_test_fixture.h>

#include <esperanza/settings.h>
#include <rpc/server.h>
#include <wallet/db.h>
#include <wallet/rpcvalidator.h>

WalletTestingSetup::WalletTestingSetup(const bool isValidator, const std::string& chainName):
    TestingSetup(chainName)
{
    bitdb.MakeMock();

    bool fFirstRun;
    g_address_type = OUTPUT_TYPE_DEFAULT;
    g_change_type = OUTPUT_TYPE_DEFAULT;
    std::unique_ptr<CWalletDBWrapper> dbw(new CWalletDBWrapper(&bitdb, "wallet_test.dat"));

    esperanza::Settings settings = esperanza::Settings::Default();
    settings.m_validating = isValidator;
// UNIT-E TODO: use proper settings class for this
//    settings.m_proposing = !isValidator;

    pwalletMain = MakeUnique<CWallet>(settings, std::move(dbw));
    pwalletMain->LoadWallet(fFirstRun);
    vpwallets.insert(vpwallets.begin(), &*pwalletMain);
    RegisterValidationInterface(pwalletMain.get());

    RegisterWalletRPCCommands(tableRPC);
    RegisterValidatorRPCCommands(tableRPC);
}

WalletTestingSetup::~WalletTestingSetup()
{
    UnregisterValidationInterface(pwalletMain.get());
    vpwallets.clear();
    bitdb.Flush(true);
    bitdb.Reset();
}
