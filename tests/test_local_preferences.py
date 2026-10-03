import copy
import unittest
from unittest.mock import Mock

from StockTradingSim import PortfolioStore


class LocalPreferenceTests(unittest.TestCase):
    def make_store(self):
        store = PortfolioStore.__new__(PortfolioStore)
        store.data = store._default()
        store.save = Mock()
        return store

    def test_defaults_and_old_config_migrate_to_only_chan(self):
        store = self.make_store()
        self.assertEqual(store.data['strategy_settings']['enabled_ids'], ['chan_daily'])
        store.data['strategy_settings'] = {'enabled_ids': ['market_gate', 'canslim_radar'], 'active_pack': 'canslim_discipline'}
        self.assertEqual(store.strategy_config()['enabled_ids'], ['chan_daily'])
        self.assertEqual(store.strategy_config()['active_pack'], 'chan_daily')
        self.assertFalse(store.strategy_config()['local_auto_submit'])

    def test_later_user_strategy_choices_are_not_overwritten(self):
        store = self.make_store()
        store.strategy_config()
        store.set_enabled_strategies(['market_gate'])
        self.assertEqual(store.strategy_config()['enabled_ids'], ['market_gate'])

    def test_risk_migration_retains_only_fixed_three_order_limit(self):
        store = self.make_store()
        store.data['risk'] = {'block_st_buy': True, 'max_position_pct': 20,
                              'enabled': False, 'max_pending_per_code': 10}
        self.assertEqual(store.risk_config(), {'max_pending_per_code': 3})
        store.set_risk_config({'enabled': False, 'max_pending_per_code': 100})
        self.assertEqual(store.risk_config(), {'max_pending_per_code': 3})

    def test_new_mode_defaults_to_all_buy_sell_types_but_preserves_choice(self):
        store = self.make_store()
        self.assertEqual(store.strategy_config()['local_mode'], 'first_second_third')
        for mode in ('third_buy', 'second_third', 'first_second_third'):
            store.data['strategy_settings'] = {'local_mode': mode}
            self.assertEqual(store.strategy_config()['local_mode'], mode)

    def test_account_and_ai_are_unchanged_by_migration(self):
        store = self.make_store()
        store.data['cash'] = 12345
        store.data['trades'] = [{'action': 'BUY', 'qty': 200}]
        before = copy.deepcopy({k: store.data[k] for k in ('cash', 'trades', 'watchlist', 'ai')})
        store.strategy_config()
        store.risk_config()
        self.assertEqual(before, {k: store.data[k] for k in before})


if __name__ == '__main__':
    unittest.main()
