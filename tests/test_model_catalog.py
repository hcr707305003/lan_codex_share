import pytest
from lan_codex_share.model_catalog import ModelCatalog, PRESETS


def test_persistence_order_and_metadata(tmp_path):
    store = ModelCatalog(tmp_path / 'custom_models.json')
    store.add('new-model', '新模型')
    other = ModelCatalog(store.path)
    rows = other.merge([{'model': 'gpt-6-astra', 'supported_reasoning_efforts': [{'value': 'high'}]}])
    assert [r['model'] for r in rows[:9]] == [m for m, _ in PRESETS]
    assert rows[1]['supported_reasoning_efforts'] == [{'value': 'high'}]
    assert rows[-1]['display_name'] == '新模型'
    with pytest.raises(ValueError, match='已存在'):
        other.add('new-model', '重复')
    with pytest.raises(ValueError):
        other.add('../bad model', 'bad')
