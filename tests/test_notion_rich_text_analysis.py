from unittest.mock import patch
from pathlib import Path
import pytest
import json

from notion_nlp.parameter.utils import load_config, load_stopwords
from notion_nlp.core.task import run_task, run_all_tasks, check_resource

from notion_nlp.parameter.config import TaskParams, ConfigParams, PathParams
from notion_nlp.parameter.log import config_log
from notion_nlp.parameter.error import NLPError, ConfigError, TaskError
from notion_nlp.core.api import NotionDBText
from notion_nlp.core.nlp import NotionTextAnalysis

PROJECT_ROOT_DIR = Path(__file__).parent.parent
EXEC_DIR = Path.cwd()


@pytest.fixture
def notion_text_analysis():
    check_resource()

    config_file = PROJECT_ROOT_DIR / PathParams.notion_test_config.value
    config = load_config(config_file)

    header = config.notion.header
    task = config.tasks[0]
    task_name = task.name
    task_describe = task.describe
    database_id = task.database_id
    extra_data = task.extra

    return NotionTextAnalysis(header, task_name, task_describe, database_id, extra_data)


def test_notion_text_analysis_init(notion_text_analysis):
    assert notion_text_analysis.total_texts != []


def test_notion_text_analysis_run(notion_text_analysis):
    notion_text_analysis.run(
        stopwords=set(),
        output_dir="./results",
        top_n=5,
        split_pkg="jieba",
    )
    assert not notion_text_analysis.tf_idf_dataframe.empty


def test_notion_text_analysis_check_stopwords():
    assert NotionTextAnalysis.check_stopwords("the", {"the", "is"}) is True
    assert NotionTextAnalysis.check_stopwords("123", {"the", "is"}) is True
    assert NotionTextAnalysis.check_stopwords("", {"the", "is"}) is True
    assert NotionTextAnalysis.check_stopwords("hello", {"the", "is"}) is False


def test_notion_text_analysis_check_sentence_available():
    assert NotionTextAnalysis.check_sentence_available("#hello world!") is False
    assert NotionTextAnalysis.check_sentence_available("hello world!") is True


def test_notion_text_analysis_split_sentence():
    assert NotionTextAnalysis.split_sentence("今天天气不错，适合出去玩", "jieba") == [
        "今天天气",
        "不错",
        "，",
        "适合",
        "出去玩",
    ]


def test_notion_text_analysis_handling_sentences(notion_text_analysis):
    notion_text_analysis.total_texts = []
    with pytest.raises(NLPError):
        notion_text_analysis.handling_sentences(stopwords=set(), split_pkg="jieba")
    notion_text_analysis.total_texts = [["今天天气不错，适合出去玩", "#hello"]]
    with pytest.raises(NLPError):
        notion_text_analysis.handling_sentences(
            stopwords={"今天天气", "不错", "，", "适合", "出去玩"}, split_pkg="jieba"
        )
    notion_text_analysis.total_texts = [["#hello"]]
    with pytest.raises(NLPError):
        notion_text_analysis.handling_sentences(stopwords=set(), split_pkg="jieba")


class TestNotionDBText:
    def setup_class(self, notion_text_analysis):
        self.header = notion_text_analysis.header
        self.database_id = notion_text_analysis.database_id
        self.extra_data = notion_text_analysis.extra_data
        self.db_text = NotionDBText(self.header, self.database_id, self.extra_data)

    @patch("requests.post")
    def test_read_pages(self, mock_post):
        mock_post.return_value.text = json.dumps(
            {
                "has_more": False,
                "results": [{"id": "123"}],
                "next_cursor": "abc",
            },
            ensure_ascii=False,
        )
        pages = self.db_text.read_pages()
        assert len(pages) == 1
        assert pages[0]["id"] == "123"

    @patch("requests.get")
    def test_read_blocks(self, mock_get):
        mock_get.return_value.text = json.dumps(
            {"results": [{"id": "456"}]}, ensure_ascii=False
        )
        blocks = self.db_text.read_blocks([{"id": "123"}])
        assert len(blocks) == 1
        assert len(blocks[0]) == 1
        assert blocks[0][0]["id"] == "456"

    def test_read_rich_text(self):
        blocks = [
            [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "test"}]}}]
        ]
        texts = self.db_text.read_rich_text(blocks)
        assert len(texts) == 1
        assert len(texts[0]) == 1
        assert texts[0][0] == "test"


@pytest.fixture
def mock_task():
    # 定义一个mock task用于测试
    return TaskParams(
        name="test", describe="testing", database_id="123", extra=[], run=True
    )


def test_run_task_inputs(mock_task, notion_text_analysis):
    # 测试函数输入的参数和异常情况
    with pytest.raises(ConfigError, match="Task or Task Name, there must be one."):
        run_task(
            task=None,
            task_json=None,
            task_name=None,
            config_file=notion_text_analysis.config_file,
        )

    with pytest.raises(ConfigError, match="Invalid task json."):
        run_task(task_json="{invalid json}", config_file=notion_text_analysis.config_file)

    with pytest.raises(TaskError, match="nonexistent does not exist."):
        run_task(task_name="nonexistent", config_file=notion_text_analysis.config_file)

    with pytest.raises(
        TaskError,
        match="discarded_task has been set to stop running. Check the parameters.",
    ):
        mock_task.run = False
        run_task(task_name="discarded_task", config_file=notion_text_analysis.config_file)

    with pytest.raises(ConfigError, match="Token is required."):
        run_task(task_json="{valid json}", config_file="nonexistent")


def test_run_task_outputs(notion_text_analysis):
    import shutil

    # 测试函数输出的结果类型和内容是否正确
    output_dir = Path("./unittest_results")
    while output_dir.exists():
        output_dir = output_dir / "subdir"
    run_task(
        task=notion_text_analysis.task,
        config_file=notion_text_analysis.config_file,
        output_dir=output_dir.as_posix(),
    )

    # 测试输出结果是否正确
    # 此处的假设是notion_text_analysis.run()会在output_dir下生成一个文件
    assert (
        output_dir
        / f"{notion_text_analysis.task_name}.tf_idf.analysis_result.top5_word_with_sentences.md"
    ).exists()
    # 删除文件
    shutil.rmtree(output_dir)


def test_run_task_subfunctions(mock_task):
    # 测试函数调用的子函数能否正常调用并返回正确的结果
    config_file = "configs/notion.test.yaml"
    stopfiles_dir = "resources/stopwords"
    stopfiles_postfix = "stopwords.txt"

    config = load_config(config_file)
    assert isinstance(config, ConfigParams)

    stopfiles = load_stopwords(stopfiles_dir, stopfiles_postfix, False)
    assert isinstance(stopfiles, set)


def test_run_task_edge_cases(mock_task):
    # 测试函数在一些边界情况下是否能够正常工作
    with pytest.raises(ValueError, match="top_n must be a positive integer"):
        run_task(task=mock_task, top_n=-1)

    with pytest.raises(ValueError, match="top_n must be a positive integer"):
        run_task(task=mock_task, top_n=0)


def test_run_all_tasks():
    # 测试从文件运行
    run_all_tasks(config_file=PROJECT_ROOT_DIR / PathParams.notion_test_config.value)


if __name__ == "__main__":
    config_log(
        EXEC_DIR.stem,
        "unit_test",
        log_root=(EXEC_DIR / PROJECT_ROOT_DIR.name / "logs").as_posix(),
        print_terminal=True,
        enable_monitor=False,
    )
    pytest.main(["-v", "-s", "-q", "test_notion_nlp.py"])
