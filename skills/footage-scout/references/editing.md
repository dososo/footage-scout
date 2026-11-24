# 交给剪辑,再收回来

适用于任何剪辑工具(HyperFrames、Remotion、ffmpeg 脚本、剪辑软件)。

## 剪辑前

调 `build_credits(edit_plan=true)`(CLI:`fsc edit plan <项目目录>`),得到 `edit_plan.json`。只用里面的 `clips`;`left_out` 里的不能用,把原因告诉用户。

| 字段 | 用法 |
|---|---|
| `path` | 相对项目目录的文件 |
| `sha256` | 剪辑前后都不变;要改画面就另存,不覆盖原文件 |
| `media` | 时长、宽高、帧率,可能为空 |
| `segment` | 已截片时的入出点 |
| `rules` | 见下表 |

| rule | 含义 |
|---|---|
| `no_edit` | 不能剪、裁、调色 |
| `no_ai_edit` | 不能用 AI 改画面 |
| `disclose_ai_edit` | 用 AI 改了要写明 |
| `credit` | 成片要署名 |
| `check_third_party` | 音乐、人物、商标可能另有权利,发布前由用户确认 |

## 剪辑后

在项目目录写 `edit_report.json`,再调 `build_credits(edit_report="edit_report.json")`(CLI:`fsc edit apply <项目目录> --report <文件>`)。它会把改动写进 manifest 的 `modifications` 并重写 `CREDITS.md`。

```json
{
  "schema_version": "1.0.0",
  "brief_sha256": "抄 edit_plan.json 里的值",
  "items": [
    {"asset_id": "nps:...", "sha256": "抄 edit_plan.json 里的值", "changes": [{"kind": "trim", "detail": "2.0-7.0 s"}, {"kind": "color"}]}
  ]
}
```

`kind` 只能是:`trim`、`crop`、`scale`、`speed`、`color`、`stabilize`、`denoise`、`audio_removed`、`audio_replaced`、`overlay`、`composite`、`ai_edit`、`other`。

- 如实写,没做的不写。没用上的素材不写进 `items`。
- 报错就改报告,不要改 manifest。整份报告要么全部写入,要么都不写;重复提交不会重复记录。
- 报告不能改许可和门禁结果。
