import os
import subprocess
from pathlib import Path
import json
import argparse
import shutil


def read_config():
    # Read configuration from local file system
    # For cloud function replace with reading from secrets manager
    with open(os.path.expanduser('~/.mettalex/config-dev.json'), 'r') as f:
        config = json.load(f)
    return config


def connect(network, account='user'):
    if network == 'local':
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        try:
            w3.eth.defaultAccount = w3.eth.accounts[0]
            admin = w3.eth.accounts[0]
        except:
            raise Exception("Ensure ganache-cli is connected")
    elif network == 'bsc-testnet':
        config = read_config()
        os.environ['WEB3_PROVIDER_URI'] = 'https://data-seed-prebsc-1-s1.binance.org:8545/'
        os.environ['WEB3_CHAIN_ID'] = '97'

        from web3.middleware import construct_sign_and_send_raw_middleware
        from web3.middleware import geth_poa_middleware
        from web3.auto import w3

        admin = w3.eth.account.from_key(config[account]['key'])
        w3.eth.defaultAccount = admin.address
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(admin))

    elif network == 'kovan':
        config = read_config()
        os.environ['WEB3_INFURA_PROJECT_ID'] = config['infura']['project_id']
        os.environ['WEB3_INFURA_API_SECRET'] = config['infura']['secret']

        from web3.middleware import construct_sign_and_send_raw_middleware
        from web3.auto.infura.kovan import w3

        admin = w3.eth.account.from_key(config[account]['key'])
        w3.eth.defaultAccount = admin.address
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(admin))
    else:
        raise ValueError(f'Unknown network {network}')

    assert w3.isConnected()
    return w3, admin


def get_contracts(w3):
    """
        make --directory=mettalex-balancer deploy_pool_factory
        make --directory=mettalex-balancer deploy_balancer_amm
    #	make --directory=mettalex-coin deploy  # NB: Pool controller fails if actual USDT contract is used
        make --directory=mettalex-vault deploy_coin
        make --directory=mettalex-vault deploy_long
        make --directory=mettalex-vault deploy_short
        make --directory=mettalex-vault deploy_vault
        make --directory=mettalex-yearn deploy_controller
        make --directory=mettalex-yearn deploy_vault
        make --directory=pool-controller deploy
        :return:
    """
    bfactory_build_file = Path(
        __file__).parent / 'mettalex-balancer' / 'build' / 'contracts' / 'BFactory.json'
    bpool_build_file = Path(
        __file__).parent / 'mettalex-balancer' / 'build' / 'contracts' / 'BPool.json'

    # Use Mettalex vault version of CoinToken rather than USDT in mettalex-coin to avoid Solidity version issue
    coin_build_file = Path(__file__).parent / 'mettalex-vault' / \
        'build' / 'contracts' / 'CoinToken.json'
    # Use position token for both long and short tokens
    position_build_file = Path(
        __file__).parent / 'mettalex-vault' / 'build' / 'contracts' / 'PositionToken.json'
    mettalex_vault_build_file = Path(
        __file__).parent / 'mettalex-vault' / 'build' / 'contracts' / 'Vault.json'

    yvault_controller_build_file = Path(
        __file__).parent / 'mettalex-yearn' / 'build' / 'contracts' / 'Controller.json'
    yvault_build_file = Path(
        __file__).parent / 'mettalex-yearn' / 'build' / 'contracts' / 'yVault.json'

    # May need to deploy pool controller via openzeppelin cli for upgradeable contract
    pool_controller_build_file = Path(
        __file__).parent / 'pool-controller' / 'build' / 'contracts' / 'StrategyBalancerMettalex.json'

    contracts = {
        'BFactory': create_contract(w3, bfactory_build_file),
        'BPool': create_contract(w3, bpool_build_file),
        'Coin': create_contract(w3, coin_build_file),
        'Long': create_contract(w3, position_build_file),
        'Short': create_contract(w3, position_build_file),
        'Vault': create_contract(w3, mettalex_vault_build_file),
        'YController': create_contract(w3, yvault_controller_build_file),
        'YVault': create_contract(w3, yvault_build_file),
        'PoolController': create_contract(w3, pool_controller_build_file),
    }
    return contracts


def create_contract(w3, build_file):
    with open(build_file, 'r') as f:
        contract_details = json.load(f)
    abi = contract_details['abi']
    bytecode = contract_details['bytecode']
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    return contract


def deploy_contract(w3, contract, *args):
    tx_hash = contract.constructor(*args).transact()
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    deployed_contract = w3.eth.contract(
        address=tx_receipt.contractAddress,
        abi=contract.abi
    )
    return deployed_contract


def connect_contract(w3, contract, address):
    """Connect to existing deployed contract

    :param w3:
    :param contract:
    :param address:
    :return:
    """
    deployed_contract = w3.eth.contract(
        address=address,
        abi=contract.abi
    )
    return deployed_contract


def connect_deployed(w3, contracts, contract_file='contract_address.json', cache_file='contract_cache.json'):
    if not os.path.isfile(contract_file):
        print('No address file')
        return
    if not os.path.isfile('args.json'):
        print('No args file')
        return

    with open('args.json', 'r') as f:
        args = json.load(f)
    with open(contract_file, 'r') as f:
        contract_cache = json.load(f)

    network = get_network(w3)

    deployed_contracts = {}

    for k in contracts.keys():
        if contract_cache[k]:
            deployed_contracts[k] = connect_contract(
                w3, contracts[k], contract_cache[k])

        else:
            if k == 'BPool':
                deployed_contracts[k] = create_balancer_pool(
                    w3, contracts[k], connect_contract(w3, contracts['BFactory'], contract_cache['BFactory']))

            elif k == 'YController':
                deployed_contracts[k] = deploy_contract(
                    w3, contracts[k], w3.eth.defaultAccount)

            elif k == 'YVault':
                deployed_contracts[k] = deploy_contract(
                    w3, contracts[k], contract_cache['Coin'], contract_cache['YController'])

            elif k == 'PoolController':
                deployed_contracts[k] = deploy_contract(
                    w3, contracts[k], contract_cache['YController'], contract_cache['Coin'], contract_cache['BPool'], contract_cache['Vault'], contract_cache['Long'], contract_cache['Short'])
            else:
                deployed_contracts[k] = deploy_contract(
                    w3, contracts[k], *args[network][k])
        contract_cache[k] = deployed_contracts[k].address

    with open(cache_file, 'w') as f:
        json.dump(contract_cache, f)
    return deployed_contracts


def deploy(w3, contracts, cache_file='contract_cache.json'):
    acct = w3.eth.defaultAccount
    balancer_factory = deploy_contract(w3, contracts['BFactory'])
    balancer = create_balancer_pool(w3, contracts['BPool'], balancer_factory)
    coin = deploy_contract(w3, contracts['Coin'], 'Tether USD', 'USDT', 18)
    tok_version = 1
    ltk = deploy_contract(
        w3, contracts['Long'], 'Long Position', 'LTOK', 6, tok_version)
    stk = deploy_contract(
        w3, contracts['Short'], 'Short Position', 'STOK', 6, tok_version)
    vault = deploy_contract(
        w3, contracts['Vault'],
        'Mettalex Vault', tok_version, coin.address, ltk.address, stk.address,
        acct, balancer.address, 3000000, 2000000, 100000000, 300
    )
    y_controller = deploy_contract(w3, contracts['YController'], acct)
    y_vault = deploy_contract(
        w3, contracts['YVault'], coin.address, y_controller.address)

    strategy = deploy_contract(
        w3, contracts['PoolController'], y_controller.address, coin.address, balancer.address, vault.address, ltk.address, stk.address)

    contract_addresses = {
        'BFactory': balancer_factory.address,
        'BPool': balancer.address,
        'Coin': coin.address,
        'Long': ltk.address,
        'Short': stk.address,
        'Vault': vault.address,
        'YVault': y_vault.address,
        'YController': y_controller.address,
        'PoolController': strategy.address
    }
    with open(cache_file, 'w') as f:
        json.dump(contract_addresses, f)

    deployed_contracts = {
        'BFactory': balancer_factory,
        'BPool': balancer,
        'Coin': coin,
        'Long': ltk,
        'Short': stk,
        'Vault': vault,
        'YVault': y_vault,
        'YController': y_controller,
        'PoolController': strategy
    }
    return deployed_contracts


def create_balancer_pool(w3, pool_contract, balancer_factory):
    acct = w3.eth.defaultAccount
    tx_hash = balancer_factory.functions.newBPool().transact(
        {'from': acct, 'gas': 5_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    # Find pool address from contract event
    receipt = balancer_factory.events.LOG_NEW_POOL().processReceipt(tx_receipt)
    pool_address = receipt[0]['args']['pool']
    balancer = w3.eth.contract(
        address=pool_address,
        abi=pool_contract.abi
    )
    return balancer


def get_network(w3):
    chain_id = w3.eth.chainId
    network = 'development'
    if chain_id == 42:
        network = 'kovan'
    elif chain_id == 95:
        network = 'bsc-testnet'
    return network


def upgrade_strategy(w3, contracts, strategy, y_controller, coin, balancer, vault, ltk, stk):
    # deploy new strategy
    new_strategy = deploy_contract(
        w3,
        contracts['PoolController'],
        y_controller.address,
        coin.address,
        balancer.address,
        vault.address,
        ltk.address,
        stk.address
    )

    # setStrategy
    set_strategy(w3, y_controller, coin, new_strategy)

    # update pool controller from old strategy
    update_pool_controller(w3, balancer, strategy, new_strategy)

    strategy = connect_strategy(w3, new_strategy.address)
    return strategy


def connect_strategy(w3, address):
    build_file = Path(__file__).parent / 'pool-controller' / \
        'build' / 'contracts' / 'StrategyBalancerMettalex.json'
    with open(build_file, 'r') as f:
        contract_details = json.load(f)

    # get abi
    abi = contract_details['abi']
    strategy = w3.eth.contract(abi=abi, address=address)
    return strategy


def full_setup(w3, admin, deployed_contracts=None, price=None):
    if deployed_contracts is None:
        print('Deploying contracts')
        deployed_contracts = deploy(w3, contracts)
    print('Whitelisting Mettalex vault to mint position tokens')
    whitelist_vault(
        w3, deployed_contracts['Vault'], deployed_contracts['Long'], deployed_contracts['Short'])
    print('Setting strategy')
    set_strategy(
        w3, deployed_contracts['YController'], deployed_contracts['Coin'], deployed_contracts['PoolController'])
    print('Setting y-vault controller')
    set_yvault_controller(
        w3, deployed_contracts['YController'], deployed_contracts['YVault'].address, deployed_contracts['Coin'].address)
    print('Setting balancer controller')
    set_balancer_controller(
        w3, deployed_contracts['BPool'], deployed_contracts['PoolController'])
    print('Setting Mettalex vault AMM')
    set_autonomous_market_maker(
        w3, deployed_contracts['Vault'], deployed_contracts['PoolController'])  # Zero fees for AMM
    if price is not None:
        # May be connecting to existing vault, if not then can set tht price here
        set_price(w3, deployed_contracts['Vault'], price)
    return w3, admin, deployed_contracts


def whitelist_vault(w3, vault, ltk, stk):
    set_token_whitelist(w3, ltk, vault.address, True)
    set_token_whitelist(w3, stk, vault.address, True)


def set_token_whitelist(w3, tok, address, state=True):
    acct = w3.eth.defaultAccount
    old_state = tok.functions.whitelist(address).call()
    tx_hash = tok.functions.setWhitelist(address, state).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    new_state = tok.functions.whitelist(address).call()
    tok_name = tok.functions.name().call()
    print(f'{tok_name} whitelist state for {address} changed from {old_state} to {new_state}')


def set_strategy(w3, y_controller, tok, strategy):
    acct = w3.eth.defaultAccount
    old_strategy = y_controller.functions.strategies(tok.address).call()
    tx_hash = y_controller.functions.setStrategy(tok.address, strategy.address).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    new_strategy = y_controller.functions.strategies(tok.address).call()
    tok_name = tok.functions.name().call()
    print(f'{tok_name} strategy changed from {old_strategy} to {new_strategy}')


def update_pool_controller(w3, balancer, strategy, new_strategy):
    acct = w3.eth.defaultAccount
    old_balancer_controller = balancer.functions.getController().call()
    tx_hash = strategy.functions.updatePoolController(new_strategy.address).transact({
        'from': acct, 'gas': 1_000_000})
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    new_balancer_controller = balancer.functions.getController().call()
    print(
        f'BPool controller changed from {old_balancer_controller} to {new_balancer_controller}')


def set_yvault_controller(w3, y_controller, y_vault_address, token_address):
    acct = w3.eth.defaultAccount
    tx_hash = y_controller.functions.setVault(
        token_address, y_vault_address).transact({'from': acct, 'gas': 1_000_000})
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    print('yVault added in yController')


def set_balancer_controller(w3, balancer, strategy, controller_address=None):
    acct = w3.eth.defaultAccount
    if controller_address is None:
        controller_address = strategy.address
    tx_hash = balancer.functions.setController(controller_address).transact({
        'from': acct, 'gas': 1_000_000})
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    balancer_controller = balancer.functions.getController().call()
    print(f'Balancer controller {balancer_controller}')


def set_autonomous_market_maker(w3, vault, strategy):
    acct = w3.eth.defaultAccount
    old_amm = vault.functions.ammPoolController().call()
    tx_hash = vault.functions.updateAMMPoolController(strategy.address).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    new_amm = vault.functions.ammPoolController().call()
    vault_name = vault.functions.contractName().call()
    print(f'{vault_name} strategy changed from {old_amm} to {new_amm}')


def set_price(w3, vault, price):
    acct = w3.eth.defaultAccount
    old_spot = vault.functions.priceSpot().call()
    tx_hash = vault.functions.updateSpot(price).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    new_spot = vault.functions.priceSpot().call()
    vault_name = vault.functions.contractName().call()
    print(f'{vault_name} spot changed from {old_spot} to {new_spot}')


def get_vault_details(w3, contracts, address=None):
    vault_contract = contracts['Vault']
    if address is None:
        address = vault_contract.address

    vault = w3.eth.contract(address=address, abi=vault_contract.abi)

    coin_address = vault.functions.collateralToken().call()
    coin = w3.eth.contract(address=coin_address, abi=contracts['Coin'].abi)
    ltok_address = vault.functions.longPositionToken().call()
    ltok = w3.eth.contract(address=ltok_address, abi=contracts['Long'].abi)
    stok_address = vault.functions.shortPositionToken().call()
    stok = w3.eth.contract(address=stok_address, abi=contracts['Short'].abi)

    name = vault.functions.contractName().call()
    vault_floor = vault.functions.priceFloor().call()
    vault_cap = vault.functions.priceCap().call()
    collateral_per_unit = vault.functions.collateralPerUnit().call()
    vault_spot = vault.functions.priceSpot().call()
    vault_details = {
        'vault': vault,
        'coin': coin,
        'ltok': ltok,
        'stok': stok,
        'name': name,
        'floor': vault_floor,
        'cap': vault_cap,
        'spot': vault_spot,
        'cpu': collateral_per_unit
    }
    return vault_details


def print_mettalex_vault(w3, contracts, address=None):
    res = get_vault_details(w3, contracts, address)

    print(f'{res["name"]}')
    print(f'Coin: {res["coin"].address}')
    print(f'Long: {res["ltok"].address}')
    print(f'Short: {res["stok"].address}')
    print(f'Vault: {res["vault"].address}')
    print(
        f'Floor: {res["floor"]}, Cap: {res["cap"]} -> Collateral Per Unit {res["cpu"]}')
    coin_dp = res["coin"].functions.decimals().call()
    ltok_dp = res["ltok"].functions.decimals().call()
    cpu_ticks = res["cpu"] * 10**(ltok_dp - coin_dp)
    print(f'Dollar value of 1 position token pair = {cpu_ticks}')
    print(f'Current spot price: {res["spot"]}')
    print(f'Long token spot price: {res["spot"] - res["floor"]}')
    print(f'Short token spot price: {res["cap"] - res["spot"]}')


class BalanceReporter(object):
    def __init__(self, w3, coin, ltk, stk, y_vault):
        self.w3 = w3
        self.coin = coin
        self.ltk = ltk
        self.stk = stk
        self.y_vault = y_vault
        self.coin_scale = 10 ** 6
        self.ltk_scale = 10 ** 5
        self.stk_scale = 10 ** 5
        self.y_vault_scale = 10 ** 6

    def get_balances(self, address):
        coin_balance = self.coin.functions.balanceOf(address).call()
        ltk_balance = self.ltk.functions.balanceOf(address).call()
        stk_balance = self.stk.functions.balanceOf(address).call()
        y_vault_balance = self.y_vault.functions.balanceOf(address).call()
        return coin_balance, ltk_balance, stk_balance, y_vault_balance

    def print_balances(self, address, name):
        coin_balance, ltk_balance, stk_balance, y_vault_balance = self.get_balances(
            address)
        print(
            f'\n{name} ({address}) has {y_vault_balance / 10 ** 6:0.2f} vault shares')
        print(
            f'  {coin_balance / 10 ** 6:0.2f} coin, {ltk_balance / 10 ** 5:0.2f} LTK, {stk_balance / 10 ** 5:0.2f} STK\n')


def deposit(w3, y_vault, coin, amount, customAccount=None):
    acct = w3.eth.defaultAccount
    if customAccount:
        acct = customAccount
    amount_unitless = int(amount * 10 ** (coin.functions.decimals().call()))
    tx_hash = coin.functions.approve(y_vault.address, amount_unitless).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    tx_hash = y_vault.functions.deposit(amount_unitless).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    print(f'Deposit in YVault. Amount: {amount} coin. Depositer: {acct}')


def earn(w3, y_vault):
    acct = w3.eth.defaultAccount
    tx_hash = y_vault.functions.earn().transact(
        {'from': acct, 'gas': 5_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    print(f'Liquidity supplied to AMM balancer. Earn Function Caller: {acct}')


def swap_amount_in(w3, balancer, tok_in, qty_in, tok_out, customAccount=None, min_qty_out=None, max_price=None):
    acct = w3.eth.defaultAccount
    if customAccount:
        acct = customAccount
    print(
        f'User: {acct} making a swap in balancer. Token_in: ${tok_in.functions.symbol().call()} Token_out: ${tok_out.functions.symbol().call()}')
    qty_in_unitless = int(qty_in * 10 ** (tok_in.functions.decimals().call()))

    if qty_in_unitless > tok_in.functions.allowance(acct, balancer.address).call():
        tx_hash = tok_in.functions.approve(balancer.address, qty_in_unitless).transact(
            {'from': acct, 'gas': 1_000_000}
        )
        tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)

    if min_qty_out is None:
        # Default to allowing 10% slippage
        spot_price = get_spot_price(
            w3, balancer, tok_in, tok_out, unitless=False)
        print('spot price is', spot_price)
        min_qty_out = qty_in / spot_price * 0.9
        print(
            f'Minimum output token quantity not specified: using {min_qty_out}')

    if max_price is None:
        spot_price_unitless = get_spot_price(
            w3, balancer, tok_in, tok_out, unitless=True)
        max_price = int(spot_price_unitless * 1 / 0.09)
        print(f'Max price not specified: using {max_price}')

    min_qty_out_unitless = int(
        min_qty_out * 10 ** (tok_out.functions.decimals().call()))

    tx_hash = balancer.functions.swapExactAmountIn(
        tok_in.address, qty_in_unitless,
        tok_out.address, min_qty_out_unitless,
        max_price
    ).transact(
        {'from': acct, 'gas': 1_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    return tx_hash


def get_spot_price(w3, balancer, tok_in, tok_out, unitless=False, include_fee=False):
    """Get spot price for tok_out in terms of number of tok_in required to purchase
    NB: copied from setup_testnet_pool

    :param w3: Web3 connection
    :param balancer: Web3 contract for pool
    :param tok_in: Web3 contract for input token e.g. ltok to sell Long position to pool
    :param tok_out: Web3 contract for output token e.g. ctok to receive Collateral token
    :param unitless: default True, if False amount is scaled by token decimals
    :param include_fee: default True, if False ignore swap fees
    :return: number of input tokens required for each output token
        e.g. if price is $50 per long token then
            spot price  ctok -> ltok = 50 ($50 required for 1 LTK)
                        ltok -> ctok = 0.02 (0.02 LTK (20kg) required for $1)
    """
    # Spot price is number of tok_in required for 1 tok_out (unitless)
    if include_fee:
        spot_price = balancer.functions.getSpotPrice(
            tok_in.address, tok_out.address
        ).call()
    else:
        spot_price = balancer.functions.getSpotPriceSansFee(
            tok_in.address, tok_out.address
        ).call()
    if not unitless:
        # Take decimals into account
        spot_price = spot_price * 10 ** (
            tok_out.functions.decimals().call()
            - tok_in.functions.decimals().call()
            - 18)
    return spot_price


def withdraw(w3, y_vault, amount, customAccount=None):
    acct = w3.eth.defaultAccount
    if customAccount:
        acct = customAccount
    amount_unitless = amount * 10 ** (y_vault.functions.decimals().call())
    tx_hash = y_vault.functions.withdraw(amount_unitless).transact(
        {'from': acct, 'gas': 5_000_000}
    )
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    print(f'Withdraw from YVault. Amount: {amount} shares. Withdrawer: {acct}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Mettalex System Setup')
    parser.add_argument(
        '--action', '-a', dest='action', default='deploy',
        help='Action to perform: connect, deploy (default), setup'
    )
    parser.add_argument(
        '--network', '-n', dest='network', default='local',
        help='For connecting to local, kovan or bsc-testnet network'
    )

    args = parser.parse_args()
    assert args.network in {'local', 'kovan', 'bsc-testnet'}

    w3, admin = connect(args.network, 'admin')
    contracts = get_contracts(w3)

    if args.action == 'deploy':
        deployed_contracts = deploy(w3, contracts)
    elif args.action == 'connect':
        deployed_contracts = connect_deployed(w3, contracts)
    elif args.action == 'setup':
        #  will deploy and do the full setup
        w3, acc, deployed_contracts = full_setup(w3, admin)
    else:
        raise ValueError(f'Unknown action: {args.action}')

    reporter = BalanceReporter(
        w3, deployed_contracts['Long'], deployed_contracts['Long'], deployed_contracts['Short'], deployed_contracts['YVault'])

    y_vault = deployed_contracts['YVault']
    reporter.print_balances(y_vault.address, 'Y Vault')

    # Print user balance
    # reporter.print_balances(admin, 'admin')