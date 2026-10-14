#!/usr/bin/env python3
"""v2.0.0: 判定済みの評価用の文を、公開するファイルに入れていないことを見張る試験。

判定済みの評価用の文は、モデルに書かせた文章から抜き出し、人が「直す」「残す」を判定した文。これから、
直す例と残す例の評価の題材に使う。SKILL.md や references に同じ文があると、モデルは答えを読んでから
推敲することになり、評価が役に立たなくなる。試験、fixture、README などに入れても、同じ文が公開されて広まる。
例や試験には、同じ型の合成の文を使う。

この試験は、評価用の文そのものを持たない。手元の一覧から作った、文と句を正規化した SHA-256 の頭16桁だけを
持つ（JUDGED_HASHES）。公開するファイルを行ごとに文と句に分け、同じ正規化で作った値と照らす。
評価用の文の一覧がない手元でも動く。

照らす単位（pieces()）:
- 文: 行を「。」「！」「？」と表の区切り「|」で分けたもの。行の頭の箇条書きの印は外す。
- 括弧の中: 文をさらにカギ括弧、丸括弧、角括弧、引用符で分けたもの（例の表で、文をカギ括弧に入れて引くため）。
- 節: 括弧の中をさらに読点、カンマ、コロン、セミコロンで分けたもの。
正規化（normalize()）: NFKC、空白と Markdown の記号と括弧と引用符を消し、前後の読点や中黒などを外す。
Python や JSON の文字列の「\\n」は改行として扱い、JSON はほどいた文字列も照らす。

一覧に入れたもの: 判定済みの評価用の文の、文そのもの（6字以上）と括弧の中と節（10字以上）、判定のときに
示した範囲と直す案（どれも10字以上）。人が判定していない残りの文（定着した言い方の例）は文そのものだけ。
前の版の SKILL.md と references が評価用の文から取って言い換えた句も入れた。

拾えないもの（限界）: 語順や語を変えた言い換え、10字に満たない節だけを写したもの、評価用の文の一覧に
ない文（抜き出しに使った文章の、判定していない残りの文）。
"""

from pathlib import Path
import hashlib
import json
import re
import subprocess
import unicodedata
import unittest


ROOT = Path(__file__).resolve().parent.parent
THIS = Path(__file__).resolve()

SENTENCE_MIN = 6   # 文そのものを照らす最短の字数（正規化のあと）
PART_MIN = 10      # 括弧の中と節を照らす最短の字数

_SENTENCE_SPLIT = re.compile(r"[。!?|]")                    # NFKC のあと（！？｜は半角になる）
_BRACKET_SPLIT = re.compile(r"[「」『』()\[\]【】〈〉《》\"“”‘’']")
_CLAUSE_SPLIT = re.compile(r"[、,:;]")                      # NFKC のあと（，：；は半角になる）
_DROP = re.compile(r"[\s*`#>_~「」『』()\[\]【】〈〉《》\"“”‘’'|]")
_LIST_MARK = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_EDGE = "、,.:;・-…=/\\"

TEXT_SUFFIXES = (".md", ".py", ".json", ".jsonl", ".txt", ".csv", ".toml", ".yaml", ".yml", ".html", ".js")
DOC_TOPS = ("skills/yomiyasu/SKILL.md", "references/", "skills/yomiyasu/references/", "README.md", "CHANGELOG.md",
            "articles/", "evals/")
CODE_TOPS = ("tests/", "scripts/", "skills/yomiyasu/scripts/")


def normalize(text):
    """1つの文や句を照らす形にする。"""
    text = _DROP.sub("", unicodedata.normalize("NFKC", text))
    return text.strip(_EDGE)


def pieces(line):
    """1行から、文、括弧の中、節の3つの単位の (単位, 正規化した文字列) を返す。"""
    out = []
    for sentence in _SENTENCE_SPLIT.split(unicodedata.normalize("NFKC", line)):
        sentence = _LIST_MARK.sub("", sentence)
        out.append(("sentence", normalize(sentence)))
        for part in _BRACKET_SPLIT.split(sentence):
            out.append(("part", normalize(part)))
            for clause in _CLAUSE_SPLIT.split(part):
                out.append(("part", normalize(clause)))
    return [(kind, text) for kind, text in out if text]


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def source_hashes(text, sentence_min=SENTENCE_MIN, parts=True):
    """一覧を作る側: 評価用の文1つから、照らす値の集まりを作る（手元の一覧から JUDGED_HASHES を作るときに使う）。
    判定のときに示した範囲と直す案は、短い句がふつうの言い方と重なるので、sentence_min を PART_MIN にして渡す。"""
    found = set()
    for line in text.replace("\\n", "\n").split("\n"):
        for kind, piece in pieces(line):
            if kind == "sentence" and len(piece) >= sentence_min:
                found.add(digest(piece))
            elif parts and kind == "part" and len(piece) >= PART_MIN:
                found.add(digest(piece))
    return found


def json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from json_strings(key)
            yield from json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_strings(item)


def file_lines(path):
    """(行の番号, 行) を返す。JSON はほどいた文字列も、行の番号 0 として返す。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    for number, line in enumerate(text.split("\n"), 1):
        for sub in line.replace("\\n", "\n").split("\n"):
            rows.append((number, sub))
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            for value in json_strings(data):
                for sub in value.split("\n"):
                    rows.append((0, sub))
    return rows


def published_files():
    """リポジトリで追跡しているファイルと、追跡の対象になる新しいファイル（.gitignore と info/exclude で外したものを除く）。
    git がなければ DOC_TOPS と CODE_TOPS の下を見る。"""
    try:
        process = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(ROOT),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        process = None
    if process is not None and process.returncode == 0 and process.stdout:
        names = sorted(set(name for name in process.stdout.decode("utf-8").split("\0") if name))
        return [name for name in names if (ROOT / name).is_file()]
    out = []
    for top in DOC_TOPS + CODE_TOPS:
        path = ROOT / top
        if path.is_file():
            out.append(top)
        elif path.is_dir():
            out.extend(str(found.relative_to(ROOT)).replace("\\", "/") for found in sorted(path.rglob("*"))
                       if found.is_file() and "__pycache__" not in found.parts)
    return out


def files_under(tops):
    names = []
    for name in published_files():
        if (ROOT / name).resolve() == THIS or not name.endswith(TEXT_SUFFIXES):
            continue
        if any(name == top or (top.endswith("/") and name.startswith(top)) for top in tops):
            names.append(name)
    return names


def hits_in(names, hashes):
    found = []
    for name in names:
        for number, line in file_lines(ROOT / name):
            for _, piece in pieces(line):
                if len(piece) >= SENTENCE_MIN and digest(piece) in hashes:
                    found.append("{}:{} {}".format(name, number or "(JSON の値)", piece[:40]))
    return sorted(set(found))


# 判定済みの評価用の文から作った値（sha256 の頭16桁）。作り方は source_hashes()。並びは値の順。
JUDGED_HASHES_TEXT = """
006f2cdfbcb83c84 0087cb2ce147387e 028ba4e0f861a867 02f211ae2a987976
03b97574c1b40a96 04e401edfce6d66b 0670c3765e21e16e 06b4492f02a9ece5
07453cb0d4a1dace 07a5c132092aa298 0817e245fe5f78a4 082410efb404b1c1
0849b6ff508cc2f0 08fa40924ecce260 09ec973b4af59a95 0a0d012771ecd222
0a172d4754cf0d3d 0b07aaac10ce3471 0c29efce60c06511 0c7d667f63eb4989
0d70c2aebac6c24a 0dfd6e0d845317a0 0e586e7251974f07 0edb017c93e64c31
0f46323bdfb58703 0f69f3714f010639 0f6d7e526c17021c 0fd0116cd87c5426
0ff42cb1e2fdb9e6 0ff64b39636915be 106d1cf766c75f8e 109b54b2a4724e4b
109da2937759d092 10f363b7b57c3d4e 117939ee9fe4830e 1215c352a5b648fe
1262b9f7e92241d6 12cfd6c4a2f02a3a 130a94627f046b46 150b8aa32f7b5ccb
159087f0604bd805 1600169c25269939 1703d38f5f4e9799 172156a14d80530c
1773ea8b641adef2 17b5eea11751464d 185bfecb10a11a24 18ea3b4cb562bedf
1908fb21c55f2595 19601e2d325d1ef8 196ab8e5cec00fac 19a4e2fb02ca8aa0
19a857b0c08624c0 1a7f73de9a524266 1abaeabb46b800dc 1b030cc3861e9862
1c016c662a4be2e6 1c656e903dc9a2f9 1cd7028895920a32 1d9fb29327d2b00a
1e07714ac3d932c1 1eb69f11fc6d1e45 1efa6d3463cf20cb 1fa7d60f3e6cef0b
200cc2b54431df00 20367c185139cc8f 2098de24253eafc2 20e82aa08553594c
214f0eb7ed832480 22485922da246586 22dd7707e2a54599 2363ccf161c55366
24c96fe19c8b904f 254256b529471dff 259b713f52f7cec3 260168244bf47437
26b92766c15dcdf6 27e6db7de5127942 2856958cea82095b 288fac5c75dbee74
28a7d9cf70742f4f 2a2d16f91ac4a706 2ac9af3dc537f08e 2b661c3b631c0a1e
2c08a03284d767ce 2c68d9500a334063 2ca88959b91646ce 2d896fd11d145068
2dca7dd2267089b1 2e14794387abd733 2e353c7166f9ddc0 2f53f47ebe4fa521
2ff4aabe8c8a27c5 30995c223dec6a16 318d6b6b09ad4a3f 3253268c78bfb789
325ff70dc0a38188 32b5515e32d78cbf 336b7e67f8763a24 34ee41f64e8553e5
3502781f9f9b774e 35c33395b949e24c 35d445598763cbd2 36b5a4df7934a8c1
36d19e8b3bfb4146 37c5cd2bbde17364 38ae7e1667d0dea7 38c1cf2098cfdf62
392bad0577b6ca5f 3aa05167683f39dd 3b280056971b23ef 3b716a399282accb
3bcc9771a5062928 3c1d46307222245d 3c571d6d388482f8 3cd2efc3d3fe4227
3d075b101457316f 3dd26e6e33f525c4 3fa17c7182d948be 3ffe66d1a37a6c1a
401fe9ca98c68231 406cf28df436d2ac 412471ff28de6b83 420374b9b2a9d16c
434c053c769d025e 436f42e67f3bf10f 446714cffae9dfe8 446b07846cbd8b8e
4509d517fff97ba6 45f2a863dd9e5ad9 4635395737eba29f 4657b0026e01ae50
46a24c78e37d2ea3 477dd3ab0f5ef151 47e50f13b921eb16 48d55940f3601f35
49e24f7eaf33b381 4a171c5b34cb9113 4a1b36133a4ffdf0 4ac971898fea05f4
4b7b6c6dde2d1047 4c0811ce254f57f7 4d82916905da1672 4db3c85f02deb7bf
4e097964aa9ec9da 4e7424cb27e86ec0 4ebed8987da09fcf 4fec4a65c2291ee5
5152ab56ee159917 52253ab56b449e32 529e975a803a447c 52e1b774af188cab
52fc3182f278b2ea 54365eb01b51ac82 55407cfd8eeab084 55e5e619044a079c
5610c06c33a5a66c 57b84f7934579c60 5842c75a04e2f2c5 584bc34b6e42e336
58d2ef4deae700da 5a595a11535a6565 5ab4fb9a8463fbb1 5bd251f1a059c2ab
5bf2285619770c02 5c467e3d9e1e1afd 5c8b64a4a7af9027 5c9857c62542384b
5dff3365c0d36c2b 5e271af856447c90 5e97d85cb091e8dd 5ebe1cf6a0dbe971
5f1558e4d082fac6 60ff79ff85bbdfdd 61e76b566a5a2c65 62c79121899c58ed
62ff486410ebbc5f 634b8e6529286c46 63c8d5e6ff412f98 6525c3b5f40bbbcf
66b6fcee2ebd043c 6738ec3d8631af23 67d3833f942995f3 68db273e7f33a035
68faa74e311e812d 690119469952eb0e 69642ffa8e4b81ca 6b9ac41442ce57e8
6c052d5683cabcd8 6c3a386573d4b409 6cf84bd77d856278 6d08270b56d280be
6d7ccb10b9ac786e 6d7fc2a2102a5a46 6e305c2624881cb6 6e54166e5a21ff95
6eecdf40e4525257 709334cc5a49869c 71378b8cb327db5d 71791a657bc6f746
7264ee59e62940fa 728dcf7bb5983a9f 72c1045db455ad9b 73eb912c2aef80e4
7465d9cae57c22b5 74766ca0fd1ffe04 74edd65652318049 74f050dfe48c1852
752afca317b1b1e5 75b6c7ac2d3ca523 762734d3fdf15966 77ee4457beb5465f
7859abbb5ef87ce3 79dac43ff9c94526 7b06fb0f0679c49d 7e21d5caa8411171
7eab7846859df3e7 7ed5d9fb661733a0 7f37ceafff15747d 7fa1213e7dd56cb8
8002a1adb1cd3b48 80ef658ac331b6a0 813007597aee6779 81494f6994e0ecb1
81615305703fdc87 818d9e051b411de4 81cccd5503293cb3 8206dadde0f682c7
8233887230de57ea 8285a1212b788d97 831df45ea2568a30 833cfce9680589f2
8381f947600d98db 83bc240a1b7fbe92 8400c8874e1652a4 846e77078af82318
84adc55f336868b0 85287cd1903e5f95 8628448cf96f6ea7 86909ca2235f0e21
86a01641bf5722d1 86bd13b5ba4fef75 875a3b560de68df4 884c78219fd7b9a9
88748d7f347d732e 888c18f915ce184f 88bff945c50f4eca 890340e70357be21
89d6151d59c33b93 8c584020e1f211bb 8c85166d1dc74887 8dc8c6ae92bd1b45
8e2765b7486292ca 8e99f1decd203ee9 90ec23e2008e6606 9135d26be022eb33
9190e654c1f26e17 927242979af22830 9322f70bbcf64185 939ae0df26b1bfa5
9430493efe4cd16b 9463cd227fd5bbed 94687311fc2c6942 951112a5dac5be04
953c8d06c0feafd0 95c19d491b5a8141 987b37bd4aab2135 98922d19c7c537aa
9970ca025b276b64 99e2cd593e0cbc90 9b56c256da6baaec 9c1a2e6d54e4e9a2
9c4adafe8a99c9f7 9d9765ea4b6d04ca 9dd01a6be15add7b 9e6f291bb125e355
9ff0157a7333c584 a05006a2a6afa878 a05ffc92580e12cb a0f6a5f10a42a9ff
a11cc8ebfe541761 a15f17cb8380441b a293bbea7119ab34 a38c5df0608a06f4
a5de09d204c88b1c a71758527d112268 a81e056fe9c0b2a2 a848810860645e9a
a861f7ec0a870001 a9325510ca33efbf a94138a226d3ab09 aa03b429b95f5ff6
aac968e7a8247848 aada32622c38c228 ab50afeb119fd369 ab632bee5a368255
ac77d24b6f42d19a ad15ddc5722a58b3 ad6cc445d6a2b4e4 adb63eb5a0492a91
add054fc88642d5f aeb2aad6ffaea95f af1f4cde5cccfb1c af43b2655b58c736
af71e15899af2f5a afdae18f2ed9458e afe1322ca51bfbca b0b7353cab70314c
b0dd977f24fd8aca b134c3d1d192f65a b15a69112a76db9a b22ea6592431269a
b234b5381448ff16 b2c9d1d4161747ca b3a549dcced2a50c b46d815c524271e2
b53cfab5d9c1f560 b5e630f416a6b434 b69f8f297aaca2ba b6a664a86476dc29
b6d4e04e8a04a6bc b774b98215ab9481 b7abd07563e7923f b7f29f5bf7887aa1
b9223efbae95eb86 ba0db9130f96cf1e bb6a7b73a8823f03 bc5617f363a55a9b
bcf42ea3bb5d2501 bd1807977066ea3d bd393eecb9622cb5 be46fa0008ca1f61
be8b911ae3af980d bea2cb259321ba9a bed9551e68bcca3d bf2fe737c546e3e0
c02649a97282d9c7 c0485aaec3654dd7 c1f7edfbb56a3293 c22575714fffc59f
c22a9327de539d67 c2500f96195c1102 c30085381aa3e406 c334c5ed698916af
c37c3802c1b3ca8f c4e9a02015e7f3cd c5a3fd358af9e653 c6bb488f1268dcf6
c709170aa02b7e92 c7fc5aebbb586b26 c7fedf1b633ee5b5 c91e76a0186cc7cd
c939dcd56d371452 cad2ac11c88b8c65 cb587633dedb090d cb68c05fbb9e340a
cb903bd0bffe9fb3 cc38259a7fbb0a27 cc8eaa5cd516d0fc cd2f07846c4ccb2d
cd8aecb2af192fcd cf6e97680e644f18 cfdf44b4ce5cfba3 cfef8239a7d48a9f
d022ea2ed9259c01 d070395976eed2bd d0786bba00f1e73c d0e23b9dcaa8c094
d0f54fba0dc00b42 d13c6e2df57aca4c d156c46e6c6ec9ec d1b27309fbf6ba12
d1faede91abb326f d23ef1919c3ef315 d278123403464dea d58e8a7772fa9483
d6652b561403d678 d6b36f742414f676 d6efd256c4656ab8 da6224a1f09e6a3b
dabcda97e0b02075 db25c6dd6e779414 db3dc2e0f76cd327 dc90c2046d9015e9
dd244252ce229d83 de5b436ad5395224 de8bbd2556e720d3 df4cf3f26c026bc5
e00827931b4c579f e042986b54b74365 e0572a199a397552 e0a7c28a21189a44
e1305a5f35ab5b87 e24843bab91f8f59 e272de9595246cc4 e361b206406b378c
e3b6f3f73fbd0ae6 e44a9d16ad697896 e44d22e50423d11f e55b65cebe265209
e602a6842f8b609c e69c7dd95a7a93dc e70535af6c9996b3 e79c5ac57b380216
e82be32e9ed99cb7 e8a3b83c8f285e82 e8a70405d367eeac e9931950bad17999
e9cbce091e55efb1 ea26f3b6e446d576 ea49ff57f0b0cde2 eb4e216af31976ef
eba477d4e9b84af3 ebfdf1cc1a91ee39 ec20034407264347 ed2a3e81e7da394a
ede9ebe5d30d8756 ee3fd2c16bccacc5 eed1fee430b8fe0a eededd40e744cf48
ef550b9a6bf4632d ef5785093e195a86 ef962071ba915ee7 ef9d7d01f1d0a26e
f1402671aab25876 f1747f48d03c50df f1ad1e2eefcfc309 f2071649e0b94c13
f20b8c2890d2d15a f2a5632afd4b58cb f2bebc5e02b4519e f2c3c108c8803660
f365ccb74ed17391 f41154b5ffc4b548 f49661442137ea5c f53e5b5fef87bf42
f56d8cbad14a2c74 f5a480b724713980 f61472e74adb7095 f62e578f5301a781
f648befc20cff600 f6f2b85916e84713 f7beff821cdd9594 f8196b28c1e22a42
f83b5a3a4ecef5eb f8410400ea422c27 fa4920009aa17ead fa6b7600710d0efa
fa9ea9e103e98809 facdf52808a1ea21 fbeebbd7fac56053 fca1e5c40cace68d
fcc994120c08b10d fcfc3666aaa6fb4d fec5591d129c44f8 ff9ed26dc616738d
"""
JUDGED_HASHES_COUNT = 456

JUDGED_HASHES = frozenset(JUDGED_HASHES_TEXT.split())


class HashListTest(unittest.TestCase):
    def test_hash_list_shape(self):
        values = JUDGED_HASHES_TEXT.split()
        self.assertEqual(len(values), JUDGED_HASHES_COUNT)
        self.assertEqual(len(set(values)), len(values), "同じ値が2回ある")
        self.assertEqual(values, sorted(values), "値の順に並べる")
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", value) for value in values))


class PiecesTest(unittest.TestCase):
    """照らす単位の分け方（合成の文）。"""
    SENTENCE = "港の倉庫は、夜になると灯りを落とした。"

    def assertFound(self, line, sentence=None):
        wanted = source_hashes(sentence or self.SENTENCE)
        got = {digest(piece) for _, piece in pieces(line)}
        self.assertTrue(wanted & got, line)

    def test_plain_line_and_list_item(self):
        self.assertFound("港の倉庫は、夜になると灯りを落とした。翌朝、荷が届いた。")
        self.assertFound("- 港の倉庫は、夜になると灯りを落とした。")
        self.assertFound("1. 港の倉庫は、夜になると灯りを落とした。")

    def test_table_cell_and_quote(self):
        self.assertFound("| 港の倉庫は、夜になると灯りを落とした。（エッセイ） | 残す |")
        self.assertFound("- 「港の倉庫は、夜になると灯りを落とした」は、続く文で理由を書いていれば残す。")
        self.assertFound("小説の「港の倉庫は、夜になると灯りを落とした」は読み取れる。")

    def test_python_and_json_strings(self):
        self.assertFound('    ("港の倉庫は、夜になると灯りを落とした。", "港の倉庫は、夜に灯りを消した。"),')
        self.assertFound('{"text": "港の倉庫は、夜になると灯りを落とした。"}')

    def test_width_and_spaces(self):
        self.assertFound("港の倉庫は、 夜になると灯りを落とした！")
        self.assertFound("**港の倉庫は**、夜になると灯りを落とした。")

    def test_clause_of_ten_or_more(self):
        sentence = "九時を過ぎたころ、港の倉庫は静かに灯りを落とした。"
        self.assertFound("| 港の倉庫は静かに灯りを落とした | 直す |", sentence)
        short = source_hashes("九時ごろ、灯りを落とした。")
        self.assertFalse(short & {digest(piece) for _, piece in pieces("灯りを落とした")})

    def test_other_sentences_do_not_match(self):
        wanted = source_hashes(self.SENTENCE)
        got = {digest(piece) for _, piece in pieces("港の倉庫は、朝になると灯りをつけた。")}
        self.assertFalse(wanted & got)


class GuardTest(unittest.TestCase):
    """当たったら、その文を同じ型の合成の文に置き換える（判定の向き、つまり直すか残すかは変えない）。"""
    maxDiff = None

    def test_skill_references_and_documents(self):
        names = files_under(DOC_TOPS)
        self.assertIn("skills/yomiyasu/SKILL.md", names)
        self.assertTrue(any(name.startswith("references/") for name in names))
        self.assertEqual(hits_in(names, JUDGED_HASHES), [])

    def test_tests_fixtures_and_scripts(self):
        names = files_under(CODE_TOPS)
        self.assertTrue(any(name.startswith("tests/fixtures/") for name in names))
        self.assertTrue(any(name.startswith("tests/corpus/") for name in names))
        self.assertEqual(hits_in(names, JUDGED_HASHES), [])


if __name__ == "__main__":
    unittest.main()
