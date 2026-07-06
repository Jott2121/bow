# Resume does not fork

The finding this pattern's whole design rests on, and the three-call experiment that
produced it. If you are building background maintenance for headless Claude Code
sessions, this is the fact that decides your architecture.

## The tempting design

A chat agent that resumes a session per message (`claude -p --resume <sid>`) needs a
handoff brief before the session gets too big to resume. The obvious background design:
run a maintenance turn against the live session id from a side process, capture the
brief, and assume the "branch" is disposable because resuming would fork a copy.

## The experiment (3 cheap calls, ~1 minute)

1. `claude -p "Remember: the code word is BANANA." --output-format json` and keep the
   returned session id.
2. From a "background" process, resume that id: `claude -p "Also remember ORANGE. What
   is the code word?" --resume <sid>`. It answers BANANA. Note the returned session id:
   it is THE SAME id, not a fork.
3. Resume the original id again from the "main" line and ask what it was told about any
   fruit besides the code word. It knows about ORANGE.

## The result

There is no fork. The maintenance turn landed inside the one real conversation and the
session id never changed. Any background turn against a live session pollutes the main
line and races your real messages.

## What this means for your design

Never touch the session from the background. The transcript is already on disk as JSONL;
read the file instead. That is this pattern: a summarizer over the transcript file, a
cache with one writer, and an instant rotation path that consumes the cached brief. The
live session is never resumed by anything except the real conversation.

Run the three calls yourself before trusting any design that assumes forking. It costs
about a cent on the cheapest tier and it settles the question permanently.
