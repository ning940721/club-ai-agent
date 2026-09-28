from club_agent import evaluation
from club_agent.cli import main


def test_trials_roundtrip(tmp_path):
    f = tmp_path / "trials.jsonl"
    evaluation.append_trial(f, evaluation.TrialRecord(club="A", task="文案", manual_minutes=100, ai_minutes=30, fit=4))
    evaluation.append_trial(f, evaluation.TrialRecord(club="A", task="時程", manual_minutes=60, ai_minutes=30))
    trials = evaluation.load_trials(f)
    assert [round(t.time_saving, 2) for t in trials] == [0.7, 0.5]
    report = evaluation.trials_report(trials)
    assert "60.0%" in report and "達標" in report


def test_cli_offline_commands(capsys, sample_csv, tmp_path):
    main(["metrics", "--posts", str(sample_csv)])
    assert "整體平均互動率" in capsys.readouterr().out
    main(["search", "發文時間", "-k", "1"])
    assert "【" in capsys.readouterr().out
    main(["eval", "compare", "--before", str(sample_csv), "--after", str(sample_csv)])
    assert "+0.0%" in capsys.readouterr().out
    f = tmp_path / "t.jsonl"
    main(["eval", "log", "--club-name", "A", "--task", "x", "--manual", "50", "--ai", "10", "--file", str(f)])
    assert "80%" in capsys.readouterr().out
