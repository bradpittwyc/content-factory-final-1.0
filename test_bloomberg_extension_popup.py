import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright


class PopupVersionTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(channel='chrome', headless=True)
        self.page = self.browser.new_page()
        self.page.set_content('<p id="version"></p><p id="status"></p><button id="capture"></button><button id="batch"></button><button id="tech"></button><button id="stop"></button>')
        self.addCleanup(self.playwright.stop)
        self.addCleanup(self.browser.close)

    def load(self, info_response):
        self.page.evaluate('''response => {
            window.mockState = { captureStatus: '旧的批量结束' };
            window.mockActions = [];
            window.chrome = {
                storage: { local: {
                    get: async () => ({ ...window.mockState }),
                    set: async values => Object.assign(window.mockState, values)
                } },
                runtime: { sendMessage: async message => {
                    window.mockActions.push(message.action);
                    return message.action === 'info' ? response : { error: 'Tech 队列读取失败' };
                } }
            };
        }''', info_response)
        source = (Path(__file__).parent / 'bloomberg_main_extension' / 'popup.js').read_text(encoding='utf-8')
        self.page.add_script_tag(content=source)

    def test_old_worker_is_rejected_and_old_success_message_is_replaced(self):
        self.load({'error': '未知操作'})
        self.page.wait_for_function("document.getElementById('status').textContent.includes('旧版本')")
        self.page.click('#tech')
        self.assertEqual(self.page.evaluate('window.mockActions'), ['info'])
        self.assertNotIn('批量结束', self.page.locator('#status').inner_text())

    def test_action_error_survives_status_refresh(self):
        self.load({'api_version': 5, 'capture_version': 2, 'extension_version': '1.4.0'})
        self.page.wait_for_function("document.getElementById('version').textContent.includes('后台已连接')")
        self.page.click('#tech')
        self.page.wait_for_function("document.getElementById('status').textContent === 'Tech 队列读取失败'")
        self.page.wait_for_timeout(1100)
        self.assertEqual(self.page.locator('#status').inner_text(), 'Tech 队列读取失败')
        self.assertEqual(self.page.evaluate('window.mockActions'), ['info', 'tech'])

    def test_popup_closes_only_after_saved_capture(self):
        self.load({'api_version': 5, 'capture_version': 2, 'extension_version': '1.4.0'})
        self.page.wait_for_function("document.getElementById('version').textContent.includes('后台已连接')")
        self.page.evaluate('''() => {
            window.closeCount = 0;
            window.close = () => window.closeCount++;
            window.chrome.runtime.sendMessage = async () => ({ ok: true, saved: false });
        }''')
        self.page.click('#capture')
        self.assertEqual(self.page.evaluate('window.closeCount'), 0)
        self.page.evaluate('window.chrome.runtime.sendMessage = async () => ({ ok: true, saved: true })')
        self.page.click('#capture')
        self.page.wait_for_function('window.closeCount === 1')
        self.page.click('#tech')
        self.assertEqual(self.page.evaluate('window.closeCount'), 1)


if __name__ == '__main__':
    unittest.main()
