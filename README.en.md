<p align="center">
  <img src="./assets/yomiyasu_logo.jpg" alt="yomiyasu logo" width="700">
</p>

# yomiyasu

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/nanaism/yomiyasu)](https://github.com/nanaism/yomiyasu/releases)

[日本語](./README.md)

This page is a short English entry point. yomiyasu works on Japanese text only, and its instructions, check output and reports are in Japanese. The [Japanese README](./README.md) and the files in [docs/](./docs/) are the full documentation.

## What it does

yomiyasu (よみやす, "easy to read") is an agent skill that rewrites AI-generated Japanese prose to make it easier to read. It finds and rewrites unnatural metaphors, unclear subjects and predicates, tools and ideas written as if they had feelings or a will, filler phrases, and decoration such as heavy bold, bold labels with colons at the start of list items, emoji and trailing colons. It tries to leave parts that already read naturally as they are.

It tries to keep the meaning: numbers, negations, conditions, who does what, and how strongly a claim is made. Its instructions tell it not to add facts that are not in the original, the request or the material you provide, and to keep the original wording and ask the writer where the meaning cannot be decided from the text. In the comparisons below, the AI judges still found a few changes in meaning in yomiyasu's output.

It is designed mainly for practical writing such as technical articles, design documents and specifications, pull request descriptions and internal reports. It also knows thirteen document types, including mail, minutes, slides, papers, essays or fiction and scripts, and is told not to change the usual style of each type.

Since 2.0.0, the instructions tell yomiyasu to run the bundled checks on its final draft before returning it. The diff check lists changes that may alter the meaning, such as changed numbers or negations and swapped subjects and objects, as items to review. The checks look for fixed patterns only and do not decide whether the meaning was kept.

The package is a set of instructions (SKILL.md) plus these checks. In the comparisons below, AI judges rated rewriting without the skill and a few lines of instructions as easier to read than yomiyasu; see [Comparisons](#comparisons).

If your environment cannot load the full skill, two versions built from it are published in separate repositories. Both are 1.2.0, built from 2.5.0, and have not yet been updated to 3.0.0. Use the full skill when your environment can load it.

- [yomiyasu-mini](https://github.com/nanaism/yomiyasu-mini) is a skill packed into eight files, for hosts that limit the number or size of files, such as Microsoft 365 Copilot declarative agents. The full skill has many reference files, and its lint, diff and check scripts are each over 100KB. mini keeps each script at 90KB or less and each reference file at 100KB or less. It includes the meaning-change check, with the same results as the 2.5.0 diff. Its SKILL.md is 17,959 characters including the YAML front matter, which is longer than the 15,098-character SKILL.md of 3.0.0.
- [yomiyasu-pocket](https://github.com/nanaism/yomiyasu-pocket) is a 400 to 500 character instruction to paste into an AI's instructions field, such as an email app's AI or a chat app's custom instructions. It has no bundled checks.

## Install

The install commands are the same as in the [Japanese README](./README.md#インストール), which also lists the update command for each method.

```bash
# skills CLI (recommended)
npx skills add nanaism/yomiyasu

# GitHub CLI
gh skill install nanaism/yomiyasu yomiyasu

# openskills (through AGENTS.md)
npx openskills install nanaism/yomiyasu
npx openskills sync
```

To install it as a Claude Code plugin, run these two commands in Claude Code.

```text
/plugin marketplace add nanaism/yomiyasu
/plugin install yomiyasu@yomiyasu
```

When installed as a Claude Code plugin, the skill is named `yomiyasu:yomiyasu`. Use that full name, as the slash completion shows it; a user reported that plain `yomiyasu` gave "Unknown skill".

For custom skills on Claude.ai (web), upload [yomiyasu.zip](https://github.com/nanaism/yomiyasu/releases/latest/download/yomiyasu.zip) from the latest release as it is, without unpacking it. The ZIP that GitHub's "Download ZIP" button makes contains the whole repository and may be rejected.

Codex reads skills from `.agents/skills/` in the repository you work in. If you do not use the methods above, or you open the repository in Codex Cloud, copy the `skills/yomiyasu/` folder into `.agents/skills/yomiyasu/`: paste the commands below as one block in the root folder of that repository. Run the same commands again to update.

```bash
(
  set -e
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  git clone --depth 1 https://github.com/nanaism/yomiyasu "$tmp/yomiyasu"
  mkdir -p .agents/skills
  if diff -r "$tmp/yomiyasu/skills/yomiyasu" .agents/skills/yomiyasu >/dev/null 2>&1; then
    echo "Already up to date: .agents/skills/yomiyasu"; exit 0
  fi
  if [ -e .agents/skills/yomiyasu ] || [ -L .agents/skills/yomiyasu ]; then
    backup=.agents/yomiyasu.bak-$(date +%Y%m%d-%H%M%S)
    if [ -e "$backup" ]; then echo "$backup already exists. Run this again in a second." >&2; exit 1; fi
    mv .agents/skills/yomiyasu "$backup"
    echo "Moved the previous folder to $backup"
  fi
  cp -R "$tmp/yomiyasu/skills/yomiyasu" .agents/skills/yomiyasu
  echo "Installed .agents/skills/yomiyasu"
)
```

The commands fetch the latest version into a temporary folder, copy it to `.agents/skills/yomiyasu/`, and then delete the temporary folder. If `.agents/skills/yomiyasu/` already exists and differs from the latest version, they move it to `.agents/yomiyasu.bak-DATE-TIME/` instead of deleting it. If its files are exactly the same as the latest version, nothing changes. If any file in it has changed or been added since you installed it (Finder's `.DS_Store`, for example), it is moved even when the version is the same. If the download fails, they stop and leave the existing folder as it is. The backup is placed outside `.agents/skills/`, where Codex looks for skills. Each update to a new version adds one more backup folder.

To go back to the previous folder, delete the new copy and move the backup back, using the name that was printed in place of `20261024-153000`.

```bash
rm -rf .agents/skills/yomiyasu
mv .agents/yomiyasu.bak-20261024-153000 .agents/skills/yomiyasu
```

Do not commit the backup folder, and delete it when you no longer need it.

Codex then lists the skill as `yomiyasu:yomiyasu`. Call it by sending only `/yomiyasu` or by writing 「yomiyasu で」 ("with yomiyasu") in the request. Writing the listed name, `$yomiyasu:yomiyasu`, also works. The copied folder is not updated automatically; run the commands again to update.

Do not edit files inside the installed skill folder. Some install methods replace the whole folder on update, and your edits are not kept. Put project words in `.yomiyasu-words/` and your own instructions in `CLAUDE.md` or `AGENTS.md`, outside the skill folder.

## Usage

Name yomiyasu in the request and paste the draft. A request in Japanese looks like the example below.

```text
この文章を yomiyasu で読みやすくして。
（ここに修正したい文章を貼り付け）
```

The first line means "make this text easier to read with yomiyasu"; the second line is where your draft goes.

Sending only `/yomiyasu` makes the skill rewrite the text that the AI wrote in its previous answer, or the single draft (`.md` or `.txt`) directly under the working folder. When it works on a file, it does not overwrite the file and saves the final draft in the same folder under a new name.

You can tell it, in the request, the document type, how much the readers know, and who writes to whom (for example "取引先に送るメールです", an email to a client). With the relationship given, yomiyasu adjusts the politeness level the way a person in that relationship would write. If you say nothing, it infers the type from the text when it can and does not change the politeness.

When a number or condition is missing from the draft, the instructions tell yomiyasu to look for a sentence that states it in the original, the request, the material you gave, what you said in the conversation, files that were opened, or command output. It should fill the gap only when it finds such a sentence, without making it sound more certain, and otherwise leave the text as it is and ask the writer, but only where a reader could not act without the answer. The instructions say that its own earlier answers and general knowledge do not count as sources. The [comparisons](#comparisons) did not measure this, and this procedure has not yet been measured by running a model ([docs/limitations.md](./docs/limitations.md#確かめた範囲), in Japanese).

After the rewritten text, yomiyasu reports what it changed and the record of the checks it ran, and, when there is something to say, the AI-like wording it chose to keep and questions for the writer. Ask for "本文だけ" (the text only) to get the rewritten text alone; the checks still run.

Since 2.0.2, agents use yomiyasu only when you ask for it: when the request names yomiyasu, when you send `/yomiyasu`, or when you clearly ask for the Japanese proofreading skill. A request such as 「読みやすくして」 ("make it easier to read") without the name no longer selects it. If you want an agent to use yomiyasu every time it writes Japanese, add one line to your instruction file, such as `CLAUDE.md` for Claude Code or `AGENTS.md` for Codex. The section [毎回 yomiyasu を使いたいとき](./README.md#毎回-yomiyasu-を使いたいとき) ("to use yomiyasu every time") in the Japanese README has the line to paste for each host, with the skill name that each install method gives.

## Bundled tools

The skill comes with four Python scripts. They need only the Python standard library and are tested on Python 3.9 and 3.14. Their messages are in Japanese.

- `scripts/yomiyasu_lint.py` lists expressions and Markdown formatting worth reviewing in one document, line by line, such as metaphorical verbs, stock phrases, heavy bold or lists, emoji, and bold that will not render. Since 2.2.0 it also marks calques, metaphor-only headings, 「〜と言えるでしょう」, empty evaluations, vague katakana words, catchphrase commas and bare verb chains. Since 2.3.0 it also marks a transitive verb's bare stem used as a noun after 「の」 (「結果の確かめ」, 「二つの案の比べ」), which Japanese grammar research describes as hard to use; the skill rewrites it as a verb with its object or a settled Sino-Japanese noun. Since 2.4.0 it also marks a single kanji used as a noun for a short English term, such as 「版」 for "version", 「頭」 for "head" and 「印」 for "mark"; the skill writes the term people in the field use (「バージョン」, 「先頭」, 「指摘」) or asks the writer when it cannot tell what the word refers to. These marks are info only: the skill rereads the context and rewrites who does what, instead of swapping one word for another (writing the field's term for one of the single kanji above does not count as such a swap). A project word list in `.yomiyasu-words/` (`allow.txt`, `flag.txt`) removes wrong marks and adds project-specific words. With `--doc-type slides`, 2.4.0 also marks commas in headings and one-line bullets that only add a pause, such as after a sentence-initial 「だから」, a long time phrase or a short topic (`slide_comma`, info only); the skill removes those commas and keeps commas for contrast, conditions, reasons and lists.
- `scripts/yomiyasu_diff.py` compares the text before and after rewriting. It shows every change and puts changes that may alter the meaning first: numbers, negation, swapped subjects and objects, and sentence types such as hearsay, guesses and requests. Since 2.4.0 it also lists sentences where the rewrite added a person or role, as the subject or as the one to notify or ask, that is in neither the original nor the material given with `--material`.
- `scripts/yomiyasu_check.py` runs lint on the final draft and diff on the original and the final draft, and keeps a record in `.yomiyasu/` at the top of the git repository (or in the working folder outside git). `verify` checks right before submitting that the final draft is the one that was checked.
- `scripts/yomiyasu_hook.py` is an optional hook for Claude Code and Codex. It runs only if you add it to your own settings.

On Windows, run them with `py -3` instead of `python3`, as in `py -3 scripts/yomiyasu_lint.py article.md`.

```bash
python3 scripts/yomiyasu_lint.py article.md
python3 scripts/yomiyasu_lint.py article.md --fail-on warn   # exit code 1 if there are warn or error items
python3 scripts/yomiyasu_diff.py original.md rewritten.md
python3 scripts/yomiyasu_check.py run --source original.md --final final.md
python3 scripts/yomiyasu_check.py verify --final final.md
```

The scripts only report items to review and the places that changed. They do not judge whether the meaning was kept or whether the text is easy to read. `lint --json` names its score key `rule_penalty_score` (`score` up to 1.1.2) and its "no findings" key `no_rule_findings` (`is_clean` up to 1.1.2); see [docs/tools.md](./docs/tools.md#json-を前のキーの名前で読んでいたとき) for jq examples.

## Comparisons

These are the results of comparing yomiyasu with rewriting without a skill and with other methods. Every judge was an AI model, and no person has read these outputs yet. Results that are unfavorable to yomiyasu are included.

### Comparison by the author of natural-japanese (2.4.0)

The author of natural-japanese published a comparison, [推敲の比較](https://gr30zia9wv.artifactshare.link/) (in Japanese), of three conditions: natural-japanese v1.6.4, yomiyasu 2.4.0 and no skill. Claude Opus 5.5 (effort high) rewrote 12 AI-written drafts, and two AI judges, GPT-6.1 Sol and Claude Opus 5.5, rated the outputs. The method was fixed before the runs.

- In one-to-one readability comparisons over the 24 judgments of both judges, no skill beat yomiyasu 23 to 1, and 23 of the 24 three-way rankings called the difference small (「小差」). natural-japanese beat yomiyasu 18 to 6.
- The judges reported changes in meaning 2 times for yomiyasu (1 of them major), 7 times for no skill and 26 times for natural-japanese. Both yomiyasu cases came from moving a bold label into the sentence.
- The weak points the judges named for yomiyasu included removing bold labels so that the text was harder to skim (6 drafts), removing commas so that it was harder to read (5 drafts), and joining sentences into longer ones (3 drafts).
- Rewriting the 12 drafts cost $10.29 with yomiyasu and $3.39 without a skill.

### A, B and C comparison (2.5.0 and 3.0.0)

With the same 12 drafts, the same request text, and the same two judges and judging prompts as above, we compared three conditions. In every condition, Claude Code `claude -p` (Claude Opus 5.5, effort high) rewrote the 12 drafts, and the rewriting and the judging were each done twice.

- A is no skill. The agent gets only the request text. This is the same setup as "no skill" above, but the rewriting and the judging were run again, so the numbers differ.
- B is a few lines of instructions. The five lines below are placed before the request text. A new agent that had not read SKILL.md wrote them from the README and the skill description alone, and they were not edited afterwards.
- C is yomiyasu. We measured 2.5.0 and 3.0.0 separately. The 3.0.0 measured here is the published SKILL.md (15,098 characters). The selection of 3.0.0 compared a 15,000-character candidate, before three 2.5.0 rules were restored to it. Its numbers are in the 3.0.0 section of [CHANGELOG.md](./CHANGELOG.md).

<details>
<summary>The five lines given to B (in Japanese)</summary>

```text
AIが書いた日本語の下書きを、意味を変えずに読みやすく直してください。
分かりにくい比喩や大げさな言い回しはふつうの言葉にし、誰が何をするのかがはっきり分かる文にしてください。
太字や記号などの飾りは、必要な分だけにしてください。
原文にない情報は足さないでください。意味がはっきりしない所は無理に直さず、最後に確認したい点として教えてください。
自然に読める所は、そのままで構いません。
```

They ask the agent to make the draft easier to read without changing the meaning, to put unclear metaphors and overstated phrases in plain words, to make clear who does what, to keep bold and other decoration to what is needed, to add no information that is not in the original, to leave unclear parts alone and list them at the end as points to check, and to leave parts that read naturally as they are.
</details>

For readability, each judge saw the three outputs for a draft without the condition names and ranked them (1 is best, 3 is worst). The ranks are taken within a set of three, so the values for A and B also change between the set with 2.5.0 as C and the set with 3.0.0 as C.

| Set | Judge | A | B | C |
|---|---|---|---|---|
| A, B, 2.5.0 (run 1) | GPT-6.1 Sol | 1.58 | 1.58 | 2.83 |
| A, B, 2.5.0 (run 1) | Claude Opus 5.5 | 1.17 | 2.00 | 2.83 |
| A, B, 2.5.0 (run 2) | GPT-6.1 Sol | 1.58 | 1.50 | 2.92 |
| A, B, 2.5.0 (run 2) | Claude Opus 5.5 | 1.08 | 1.92 | 3.00 |
| A, B, 3.0.0 (run 1) | GPT-6.1 Sol | 1.50 | 1.58 | 2.92 |
| A, B, 3.0.0 (run 1) | Claude Opus 5.5 | 1.25 | 1.83 | 2.92 |
| A, B, 3.0.0 (run 2) | GPT-6.1 Sol | 1.67 | 1.42 | 2.92 |
| A, B, 3.0.0 (run 2) | Claude Opus 5.5 | 1.08 | 1.92 | 3.00 |

Wins and losses were counted one-to-one over the 24 judgments of both judges in each run, 48 over the two runs. Each cell gives the wins and losses of the condition named first.

| Pair | Run 1 | Run 2 | Both runs |
|---|---|---|---|
| A vs 2.5.0 | 22-2 | 23-1 | 45-3 |
| B vs 2.5.0 | 22-2 | 24-0 | 46-2 |
| A vs 3.0.0 | 23-1 | 23-1 | 46-2 |
| B vs 3.0.0 | 23-1 | 24-0 | 47-1 |

A beat B 17 to 7 in both runs of the sets with 2.5.0, and 16 to 8 in both runs of the sets with 3.0.0. All 96 rankings in the four sets called the difference small.

Each cell below gives run 1, then run 2.

| | A no skill | B few lines | C 2.5.0 | C 3.0.0 |
|---|---|---|---|---|
| Changes in meaning reported (both judges combined, major ones in parentheses) | 14 (1), 12 (0) | 44 (5), 42 (2) | 1 (1), 1 (0) | 4 (1), 0 (0) |
| Possible meaning changes found by the bundled diff | 25, 22 | 59, 57 | 7, 7 | 6, 11 |
| Edit rate (difference between original and output, mean of 12) | 5.4%, 4.9% | 8.8%, 8.3% | 1.6%, 1.9% | 2.0%, 1.7% |
| Bold count (105 in the originals) | 110, 113 | 15, 25 | 38, 34 | 29, 28 |
| Total cost for 12 drafts | $2.60, $2.66 | $2.80, $2.92 | $10.16, $10.48 | $7.32, $7.29 |
| Mean time per draft | 43 s, 50 s | 51 s, 59 s | 91 s, 109 s | 112 s, 106 s |
| Median number of turns | 3, 3 | 3, 3 | 12, 11.5 | 13, 14 |
| Median input tokens | 61k, 62k | 60k, 64k | 504k, 534k | 350k, 321k |

In run 1, 12 of B's 44 reported changes in meaning came from one draft, the essay. C runs the same diff while rewriting, so the diff row favors C.

Single runs vary under the same conditions. Over the six yomiyasu runs (2.5.0, 3.0.0 and the selected 15,000-character candidate, twice each), reported changes in meaning ranged from 0 to 4 and diff findings from 5 to 11. The one major finding for 3.0.0 in run 1 was in a technical article, where 「ノード起動待ちの時間を削ぎ落としました」 (cut down the wait for nodes to start) became 「なくしました」 (eliminated it), which makes the claim stronger. In run 2 of 2.5.0 (minor) and run 2 of the candidate (major), the same sentence was rewritten as 「省きました」 (omitted it) and flagged for the same strengthening. The wording differs, but yomiyasu has made this error on this sentence since 2.5.0.

### Audit with the critique article's ABC prompt (2.5.0)

[An article by Amane Katagiri](https://ama.ne.jp/post/slop-skill-audit/) (in Japanese) recommends checking a writing skill by comparing a bare agent (group A), a few lines of instructions (group B) and the skill (group C). The article does not name any skill, but it describes a skill like this one, which lists many rules and changes little. We gave the article's ABC prompt unchanged to a new agent (Claude Opus 5.5) and had it audit a copy of 2.5.0. The prompt asks an agent to audit a skill and, if needed, to run a comparison with groups A and B.

The audit agent had 10 drafts rewritten once in each of the three conditions, and had Claude Opus 5.5 and Claude Sonnet 5.5 judge them without the condition names (20 judgments). The judges were told to weigh changes in meaning and added information more heavily than readability.

- A was last in all 20 judgments. The audit's request for A did not ask the agent to keep the meaning.
- The audit concluded that no difference between B and C was visible. Changes in meaning per draft were 0.40 for B and 0.30 for C, and B ranked first 15 times and C 5 times.
- Readability scores (1 to 5) were 3.90 for A, 4.20 for B and 3.85 for C.
- Per draft, C cost about 3.8 times as much as B and took about 2.2 times as long.
- On drafts written by recent models, C changed very little (one comma in the incident report, nothing in the Slack announcement).

The audit's B (six lines of instructions) was written by the audit agent after it had read SKILL.md, so it was made differently from B in the comparison above. The audit also found that the Japanese README could be read as saying that yomiyasu does better than a bare AI or earlier approaches, with no evidence for it, and that this English page stated "keeps the meaning" and "does not add facts" as if they were guarantees. 3.0.0 removes or softens that wording in both READMEs.

### What these results show

On readability alone, these AI judges rated no skill and the few lines of instructions above yomiyasu. Over both runs of the 12 drafts, 3.0.0 won 2 and lost 46 one-to-one against A, and won 1 and lost 47 against B. In the 12 drafts, the judges reported fewer changes in meaning for yomiyasu: over both runs, 26 for A and 86 for B, against 2 for 2.5.0 and 4 for 3.0.0, of which 1, 7, 1 and 1 were major. In the audit's 10 drafts, yomiyasu had about as many as B. yomiyasu also leaves a record of what was checked. On the other hand, it costs more and takes longer. Rewriting the 12 drafts with 3.0.0 cost about 30 percent less than with 2.5.0, but about 2.8 times as much as A. The median number of turns was higher for 3.0.0 than for 2.5.0.

All judges were AI models. The 12-draft comparison was run twice, and the 10-draft audit once. No person has read the 3.0.0 outputs yet. In a blind reading comparison during 2.0.0 development, the author preferred 1.1.2 in 6 of the 7 Claude Code pairs whose text differed, the in-development version in 0, with 1 tie; on Codex output it was 4 to 4 over 8 pairs ([docs/limitations.md](./docs/limitations.md#確かめた範囲)). The other 3.0.0 measurements, and the conditions that were fixed before measuring and were not met, are in [docs/limitations.md](./docs/limitations.md) and in the 3.0.0 section of [CHANGELOG.md](./CHANGELOG.md). These pages are in Japanese.

## Limits

The checks catch fixed patterns only. Places without any item still need to be read against the original.

The rewriting was checked with Claude Code and Codex on macOS through their non-interactive commands (`claude -p` and `codex exec`). Rewriting has not been tested in the interactive interfaces, in installs through the Claude Code plugin, skills CLI, GitHub CLI or openskills, in Codex Cloud, in Cursor, with the Claude.ai ZIP upload, or on Windows. After the 2.0.2 release, installing from nanaism/yomiyasu on GitHub through the Claude Code plugin, skills CLI (`npx skills add`), GitHub CLI (`gh skill install`) and openskills (`npx openskills install`) was checked up to the point where Claude Code or Codex loads the skill (for openskills, up to reading it with `npx openskills read yomiyasu`). Rewriting with the 3.0.0 SKILL.md was measured only with Claude Code `claude -p` on macOS, and not on Codex. [docs/limitations.md](./docs/limitations.md) (Japanese) lists what the checks miss and what was measured.

## License

The code and documents in this repository are released under the [MIT License](./LICENSE). The copyright and permission notice for the bundled Unicode data is in [UNICODE-LICENSE.txt](./UNICODE-LICENSE.txt).

yomiyasu is a personal project by Aiichiro Oga ([@oga_aiichiro](https://x.com/oga_aiichiro)) at ALGO ARTIS. It is not an official product of the company and does not represent its views.
