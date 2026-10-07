"""Validated Bloomberg column configuration shared by the bridge and console."""
import json
import re
from urllib.parse import urlsplit

DEFAULT_COLUMNS = {'tech': {'id': 'tech', 'name': 'Tech 科技',
                           'url': 'https://www.bloomberg.com/technology', 'enabled': True},
                   'finance': {'id': 'finance', 'name': 'Finance 金融',
                               'url': 'https://www.bloomberg.com/industries/finance', 'enabled': True},
                   'economics': {'id': 'economics', 'name': 'Economics 经济',
                                 'url': 'https://www.bloomberg.com/economics', 'enabled': True},
                   'bigtake': {'id': 'bigtake', 'name': 'Big Take',
                               'url': 'https://www.bloomberg.com/bigtake', 'enabled': True},
                   'ai-today': {'id': 'ai-today', 'name': 'AI Today',
                                'url': 'https://www.bloomberg.com/account/newsletters/ai-today', 'enabled': False,
                                'note': 'Newsletter 入口，文章发现待验证'}}


def validate_column(column):
    parsed = urlsplit(column['url'])
    if (parsed.scheme != 'https' or parsed.netloc != 'www.bloomberg.com' or
            parsed.query or parsed.fragment or not parsed.path.strip('/') or
            parsed.path.startswith(('/news/', '/opinion/articles/', '/opinion/newsletters/', '/features/'))):
        raise ValueError('专栏入口须为 https://www.bloomberg.com 的栏目页面，不可填写文章链接或带查询参数的地址')
    column_id = column.get('id') or re.sub(r'[^a-z0-9-]', '-', parsed.path.strip('/').lower()).strip('-')[:40]
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', column_id):
        raise ValueError('专栏 ID 须为 1–40 位英文小写字母、数字或连字符')
    name = column['name'].strip()
    if not name or len(name) > 80:
        raise ValueError('专栏名称须为 1–80 个字符')
    result = {'id': column_id, 'name': name, 'url': 'https://www.bloomberg.com' + parsed.path.rstrip('/'),
              'enabled': bool(column.get('enabled', False))}
    if column_id == 'ai-today':
        result['note'] = 'Newsletter 入口，文章发现待验证'
    return result


def load_columns(path):
    result = {key: dict(value) for key, value in DEFAULT_COLUMNS.items()}
    if path.exists():
        for item in json.loads(path.read_text(encoding='utf-8')):
            validated = validate_column(item)
            result[validated['id']] = validated
    return result
