# サンプル（すべて架空）

実在の答案・生徒・学校とは関係のない、説明用に作ったデータです。

- `analysis.json`：答案の分析の例（1問は「読めなかった」のまま残している）
- `print.json`：それをもとにした復習プリントの材料
- `sample-print.pdf`：`print.json` から作ったプリント

作り直すとき：

```
python3 skills/test-prep-print/scripts/build_print.py examples/print.json examples/sample-print.pdf
```
