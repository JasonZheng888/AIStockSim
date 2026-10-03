"""Offline source and packaged UI acceptance, isolated from personal accounts.

Invoke StockTradingSim.py / StockTradingSim.exe with --smoke-test. No market
requests, file-bridge commands or global hotkeys are allowed in this mode.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QTabWidget


def run(app, sim) -> int:
    output = Path(os.environ.get('AISTOCKSIM_SMOKE_DIR', Path(sim.runtime_dir()) / 'build' / 'smoke-ui')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    account = output / 'isolated-account'
    account.mkdir(exist_ok=True)
    os.environ['AISTOCKSIM_DATA_DIR'] = str(account)
    sim.CONFIG_DIR = str(account)
    for name, basename in {
        'CONFIG_FILE': 'portfolio.json', 'CODEX_ORDER_FILE': 'codex_orders.json',
        'CODEX_SNAPSHOT_FILE': 'codex_snapshot.json', 'CODEX_RESULT_FILE': 'codex_result.json',
        'CODEX_KLINE_FILE': 'codex_kline_history.json', 'TRADING_CALENDAR_FILE': 'trading_calendar.json',
        'COMPACT_CONFIG_FILE': 'compact_config.json',
    }.items():
        setattr(sim, name, str(account / basename))
    sim.LegacyStockWidget.CONFIG_DIR = str(account / 'StockWidget')
    sim.LegacyStockWidget.CONFIG_FILE = str(account / 'StockWidget' / 'SW_config.json')
    checks = []
    window = None
    try:
        # Single-shot startup network tasks and file bridge never run. The
        # repeating timers are stopped before events are processed below.
        with patch.object(sim.QTimer, 'singleShot'), \
             patch.object(sim.LegacyStockWidget.FloatLabel, '_register_hotkey'), \
             patch.object(sim.LegacyStockWidget.FloatLabel, '_refresh_from_function'), \
             patch.object(sim.QuoteService, 'fetch', return_value={}), \
             patch.object(sim.requests, 'get', side_effect=AssertionError('Network forbidden in smoke test')):
            window = sim.MainWindow()
            import StockTradingSim as helper_module
            assert helper_module is sim
            assert helper_module.CONFIG_DIR == str(account)
            window.timer.stop()
            window.codex_timer.stop()
            window.store.data['watchlist'] = ['sh603986', 'hk01810']
            window.store.data['strategy_settings']['local_auto_submit'] = False
            window.quote_cache = {
                'sh603986': sim.Quote('sh603986', '离线演示 A 股', 100.0, 1.0, 1.01,
                                     '15:00:00', 'offline smoke fixture', 'CNY', '2026-09-30'),
                'hk01810': sim.Quote('hk01810', '离线演示港股', 30.0, -0.3, -0.99,
                                     '16:00:00', 'offline smoke fixture', 'HKD', '2026-09-30'),
            }
            # Synthetic bars exercise an actual confirmed structure in the
            # strategy page. These fixtures never enter the user's cache.
            extrema = [12, 8, 11, 9, 14, 12]
            prices = [10, 11, 12]
            for left, right in zip(extrema, extrema[1:]):
                prices.extend(left + (right - left) * step / 4 for step in range(1, 5))
            prices.append(12.5)
            for code in window.store.watchlist:
                rows, day = [], date(2025, 1, 2)
                for price in prices:
                    while day.weekday() >= 5:
                        day += timedelta(days=1)
                    rows.append(sim.DailyKLine(code, day.isoformat(), price, price,
                        price + .2, price - .2, 1000, price * 1000, 0, 0, 0, 0,
                        'offline smoke fixture'))
                    day += timedelta(days=1)
                window.daily_kline_cache[code] = rows
            window.resize(1180, 800)
            window.show()
            window.render_all()
            app.processEvents()
            window.grab().save(str(output / 'main.png'))
            checks.append('main_window_constructed')

            window.enter_compact_mode()
            watch = window.compact_window
            watch.timer.stop()
            watch._keep_top_timer.stop()
            app.processEvents()
            assert watch.isVisible() and not window.isVisible()
            assert watch.codes == window.store.watchlist
            watch.grab().save(str(output / 'watch.png'))
            checks.append('transparent_watch_mode_and_watchlist')
            window.exit_compact_mode()
            app.processEvents()
            assert window.isVisible() and not watch.isVisible()
            checks.append('return_to_main_window')

            # Exercise every navigation renderer, including the live strategy
            # panel and AI pages, without touching the user's account/API key.
            for index in range(window.nav_list.count()):
                window.nav_list.setCurrentRow(index)
                window.render_current_page()
                app.processEvents()
                if window.nav_meta[index]['label'] == '策略':
                    window.local_strategy_panel.table.selectRow(0)
                    window.grab().save(str(output / 'strategy.png'))
            checks.append('all_workspace_pages_rendered')

            window.open_main_settings()
            dialog = window._settings_dialog
            app.processEvents()
            for tabs in dialog.findChildren(QTabWidget):
                for index in range(tabs.count()):
                    tabs.setCurrentIndex(index)
                    app.processEvents()
                    if hasattr(dialog, 'ensure_on_screen'):
                        dialog.ensure_on_screen()
            dialog.grab().save(str(output / 'settings.png'))
            checks.append('settings_tabs_and_screen_bounds')
            dialog.hide()
            window.save_main_window_state()
            assert (account / 'portfolio.json').exists()
            checks.append('isolated_configuration_and_window_persistence')

            summary = {'version': sim.APP_VERSION, 'ok': True, 'checks': checks,
                       'account_directory': str(account), 'network_requests': 0,
                       'submitted_orders': len(window.store.data.get('pending_orders', [])),
                       'trades': len(window.store.data.get('trades', []))}
            assert summary['submitted_orders'] == 0 and summary['trades'] == 0
            (output / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            return 0
    except Exception as exc:
        (output / 'result.json').write_text(json.dumps({'version': sim.APP_VERSION, 'ok': False,
            'checks': checks, 'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False, indent=2), encoding='utf-8')
        return 1
    finally:
        if window is not None:
            window._closing = True
            window.timer.stop()
            window.codex_timer.stop()
            window.shutdown_compact()
            window.tray.hide()
            window.hide()
