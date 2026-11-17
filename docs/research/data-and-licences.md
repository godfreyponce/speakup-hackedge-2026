# Data and licences

## The short version

- **Arti (v0 and every v2) is trained only on PERCEPT-R.** TalkBank answered on Nov 13 *(expert reply, the TalkBank director, cc PhonBank)*: models trained on its data must **not be shared publicly**, because data could be extracted from them. Use in a competition demo is fine as long as participants (judges included) **keep no copies**. So no model file goes into
  any public repo or report, and none is handed to the judges. It is never sold.
- **JIBO Kids is CC BY 4.0**: we may train on it, share the model and even sell it, with credit.
  It is the base for a clean model after Nov 20.
- **There is almost no public child speech data with errors marked.** Most such sets are private
  for ethics reasons, and PERCEPT-R is the most relevant public one, but it is mostly /r/
  *(expert reply)*. That is why more sounds wait on IRB-approved recordings or lab partnerships.

## Datasets

| Set | What it has | Licence | Status |
|---|---|---|---|
| PERCEPT-R 2.2.2py (TalkBank/PhonBank) | 173 children aged 6 to 12, about 105,000 /r/ clips, each rated rhotic or derhotic by listeners. No error type. | README says CC BY-ND 4.0; TalkBank's default is CC BY-NC-SA 4.0. Sources in [../test-set.md](../test-set.md#license). | **Answered by TalkBank, Nov 13:** no public sharing of trained models; a competition demo is fine if no one keeps a copy. The corpus creator has not replied. |
| The second PERCEPT corpus and ACAD (PhonBank) | Target word and what the child actually said, in IPA | TalkBank default unless stated | Recommended by TalkBank as the best PhonBank sets for "what the child said" *(expert reply)*. Some targets are made-up words: filter them out. ACAD's IPA (%pho) lines align one to one with the words; a few lines were being fixed *(expert reply, Nov 13)*. Browse the corpus documentation before asking more. |
| JIBO Kids (DrivenData) | Child speech with IPA transcripts | **CC BY 4.0**, confirmed by DrivenData, Nov 13 | Usable now. |
| TalkBank Children's Speech Transcripts | Phonetic transcripts | not yet published | Coming to DrivenData's platform "soon" (Nov 13). |
| Speechocean762 | Read speech with pronunciation scores | CC BY *(not checked)* | Candidate for fairness and adult tests. |
| Speech Accent Archive, CORAAL | Accented and dialect speech | NC-SA family *(not checked)* | Fairness benchmark only, noncommercial. |
| UltraSuite | Ultrasound and audio of child speech | n/a | **Not a fit**: no full set of transcriptions of what children said, and not easily shared *(expert reply)*. |
| AusKidTalk (UNSW) | Australian child speech | by agreement | Asked how to apply. Would be an accent test set. |
| ChildVox (USC, 2026) | A benchmark that bundles public and clinical child speech sets (maturity, articulation, pronunciation, fluency) | Its model card lists clinical screening and commercial use as out of scope *(not checked)* | We want its source recordings, not its model. Asked which parts mark errors. |
| /s/ recordings of 2 to 5 year olds | Rated /s/ | lab-held | At the University of Minnesota (Munson lab). For older children, the Syracuse Speech Production Lab (Preston). Both asked. |

## Ways around the data gap

- **Model to data.** A lab with private recordings runs our model on its own machines and shares
  only the overall results. The recordings never leave the lab. Asked one lab (Nov 13).
- **Template matching** for sounds with only a few examples: compare a child's word to stored good
  examples instead of training a large model. Yeung et al., SLaTE 2017,
  https://www.isca-archive.org/slate_2017/yeung17_slate.pdf *(expert reply)*.
- **Our own recordings**, after an IRB: see [recruiting.md](recruiting.md).

## Rules

- No audio or child data in git (README's data rule). This covers every set above.
- Read the licence at the original source. Third-party mirrors get it wrong (for example, one
  Hugging Face copy of EpaDB says CC BY-NC while its authors say CC BY-NC-ND).
- `arti-v0.onnx` must leave git history before the repo or a model is ever made public (#25).
