# 0016. Code chooses the recommendation; the model reads and explains

- Status: Accepted
- Date: 2026-11-23

## Context

Under ADR 0010 the model named the recommended option in `present_recommendation`, and code
refused a name that broke the rule: the cheapest in total among the options of the check's term
that fit the ceiling. Code computed the right option to refuse a wrong one, and named it in the
refusal. Measured with `scripts/tools/turn-timing.sh` on 2026-11-22: with the model's reasoning
at `low`, a turn that set a ceiling waited up to 13 s on that one comparison; at `minimal`, 6 of
15 such turns named the option already on the card, were refused, and ended with that card
unchanged. ADR 0011 had already moved an offer's arithmetic from the model to code for the same
kind of failure.

## Decision

- This replaces ADR 0010's guardrail paragraph; its loan-first flow and optional ceiling stand.
- The model turns the person's words into data (the loan, the term, the ceiling, an offer, a
  choice of option) and writes the reply. It never names the recommended option.
- Code recommends, with no model call, whenever the card no longer describes the check
  (`recommendation_due`), once a step's tools have run:
  - the preferred option is the cheapest in total among the options of the term that fit the
    ceiling, or among all of them without a ceiling; when none fits, the cheapest worst-case
    payment, marked above the ceiling; a real offer always beats an example;
  - the alternative is the next cheapest by the same rule, when there is one;
  - the card's sentence of why is Hebrew copy chosen by the rule that decided.
- The person may choose a dearer option. The model records it with `choose_option`, naming the
  option and quoting the person's words; code keeps that choice while the option stays saved and
  fits the ceiling, and returns to the rule otherwise.
- Code's recommendation reaches the model's conversation as a recorded call and its result, as a
  form offer's save does, so the model explains what the card shows, with the remedy or the
  shorter term the result names.

## Consequences

- A turn that changes the ceiling, the term or the options makes one model call fewer, and the
  model's reasoning can stay `minimal` on every call, since no call compares figures.
- The card's explanation is the same text for the same case; the chat reply carries the rest.
- `present_recommendation` and its refusals are gone; the system prompt no longer teaches the rule.
