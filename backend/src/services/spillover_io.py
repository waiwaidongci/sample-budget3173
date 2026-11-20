'''三份 CSV 资料的解析与严格校验：原分派名单、投放前双向联系、投放前点击。

缺报点击不在此处补零；缺失名单由封存完备性检查单独识别。
'''
import csv, io
from src.config.domain import DOMAIN

SP = DOMAIN['spillover']
TREATED_TOKENS = set(SP['slots']['treated'])
HOLDOUT_TOKENS = set(SP['slots']['holdout'])


def _rows(content):
    if not isinstance(content, str) or not content.strip():
        raise ValueError('文件为空，无法解析')
    text = content.lstrip('﻿')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError('缺少表头')
    return list(reader), [h.strip() for h in reader.fieldnames]


def _cell(row, candidates):
    for key in candidates:
        if key in row and str(row[key]).strip() != '':
            return str(row[key]).strip()
    return None


def parse_roster(content):
    rows, headers = _rows(content)
    if not {'id', 'slot'} <= set(headers):
        raise ValueError('原分派名单须包含 id,slot 两列')
    seen = {}
    for line, row in enumerate(rows, start=2):
        pid = _cell(row, ('id', 'ID', '人员编号'))
        slot = _cell(row, ('slot', '分派槽位'))
        if not pid:
            raise ValueError(f'名单第{line}行缺少人员 id')
        if slot not in TREATED_TOKENS | HOLDOUT_TOKENS:
            raise ValueError(f'名单第{line}行 slot 必须为 treated/holdout（或 已投/留白）')
        if pid in seen:
            raise ValueError(f'名单人员 id 重复：{pid}')
        seen[pid] = 'treated' if slot in TREATED_TOKENS else 'holdout'
    if not seen:
        raise ValueError('名单没有数据行')
    return seen


def parse_edges(content, valid_ids=None):
    rows, headers = _rows(content)
    if not {'source', 'target'} <= set(headers):
        raise ValueError('联系资料须包含 source,target 两列')
    edges = set()
    for line, row in enumerate(rows, start=2):
        a = _cell(row, ('source', 'from', '人员A'))
        b = _cell(row, ('target', 'to', '人员B'))
        if not a or not b:
            raise ValueError(f'联系资料第{line}行 source/target 不完整')
        if a == b:
            raise ValueError(f'联系资料第{line}行存在自联系：{a}')
        if valid_ids is not None and (a not in valid_ids or b not in valid_ids):
            raise ValueError(f'联系资料第{line}行人员不在名单内：{a}/{b}')
        edges.add(tuple(sorted((a, b))))
    return sorted(edges)


def parse_clicks(content, valid_ids=None):
    rows, headers = _rows(content)
    if 'id' not in headers or 'click' not in headers:
        raise ValueError('点击资料须包含 id,click 两列')
    clicks = {}
    for line, row in enumerate(rows, start=2):
        pid = _cell(row, ('id', 'ID', '人员编号'))
        raw = _cell(row, ('click', '点击'))
        if not pid:
            raise ValueError(f'点击资料第{line}行缺少人员 id')
        if valid_ids is not None and pid not in valid_ids:
            raise ValueError(f'点击资料第{line}行人员不在名单内：{pid}')
        try:
            value = int(str(raw))
        except (TypeError, ValueError):
            raise ValueError(f'点击资料第{line}行点击必须为 0/1 整数，缺报请整行省略，不得填零')
        if value not in (0, 1):
            raise ValueError(f'点击资料第{line}行点击只能为 0 或 1')
        if pid in clicks:
            raise ValueError(f'点击资料人员 id 重复：{pid}')
        clicks[pid] = value
    return clicks


def validate_correction(payload, roster=None):
    '''联系/点击更正的白名单校验。'''
    allowed = {'edge_add', 'edge_remove', 'click'}
    keys = set(payload)
    unknown = keys - allowed
    if unknown:
        raise ValueError('更正字段超出白名单：' + ','.join(sorted(unknown)))
    result = {}
    if {'edge_add', 'edge_remove'} & keys:
        for key in ('edge_add', 'edge_remove'):
            if key in payload:
                value = payload[key]
                if not (isinstance(value, list) and len(value) == 2 and all(isinstance(x, str) and x for x in value)):
                    raise ValueError(key + ' 必须为两个非空人员 id 组成的数组')
                a, b = value
                if a == b:
                    raise ValueError('联系更正不能是自联系')
                if roster is not None and (a not in roster or b not in roster):
                    raise ValueError('联系更正人员不在名单内：' + f'{a}/{b}')
                result[key] = sorted((a, b))
    if 'click' in payload:
        value = payload['click']
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
            raise ValueError('点击更正必须为 0 或 1 整数')
        result['click'] = value
    if not result:
        raise ValueError('更正内容为空')
    return result
