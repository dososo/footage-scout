# 来源说明

可自动检索和下载:NASA、Open Beelden、Internet Archive(只限 Prelinger 馆藏里写明 CC 许可的条目,一律 WARN)、ESA/Hubble、ESA/Webb、ESO、NOIRLab、ISO Republic、NPS(美国国家公园,只有单条写明公有领域的是 PASS)、USGS(只收单条写明公有领域且没有第三方配乐说明的)、NASA EOL(国际空间站延时)、Netflix Open Content(大文件,HDR / AV1 测试片)、Wikimedia Commons(用户先设置 `FSC_CONTACT_URL`)。
能检索、但门禁总是 HOLD 不能下载:Internet Archive 的 NASA 合集、美国国会图书馆 LOC(许可是自由文本,不解读)。
Internet Archive 的条目要告诉用户:「许可是上传方自己声明的,Internet Archive 不担保;片中的音乐、人物和商标可能另有权利。」
能检索但只给页面:Dareful、NASA SVS(默认跳过)。
其余来源(包括 Pexels、Pixabay、Mixkit、Coverr)只给链接,由用户下载后登记。

完整清单读 MCP 资源 `footage://sources`。每个来源有:

- `tier`:T1 官方接口;T2 读网页;T3 用户在浏览器下载;T4 只给检索入口。
- `verify_status`:`official_read` 表示读过官方条款;`probed` 表示只探测过,许可按未核实处理。
- `terms_url`:条款页,给用户核对。
- `status: blocked / excluded`:不要推荐,`notes` 里有原因。

强项:太空。中等:历史档案、美国自然与野生动物。弱项:其他地区的自然空镜、城市生活、商业人像、生活方式、本地中文题材。弱项请直接告诉用户,并给链接表。
