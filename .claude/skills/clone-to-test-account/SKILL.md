---
name: clone-to-test-account
description: Replace the test account's checks with a copy of another person's, in the local, preview and production databases. Use when asked to clone an account's checks to the test account, or to refresh the test account's copy.
---

# Clone a person's checks into the test account

The test account signs in like anyone else, so a copy of a person's checks lets the owner replay
that person's conversation as their own. The copy replaces everything the test account holds:
its checks, conversations and message count.

## The accounts

The database knows people by Google account ID, never by email. `known-users.md` at the repo
root, a local file git never sees, maps the two, and its "Test account clone" section names:

- the **test account**, the only account this skill ever writes to;
- the **default source**, used when the request names none.

This file holds no address, since the pre-commit hook refuses a commit that stages one of
`params.sh`. When `known-users.md` or its section is missing, stop and say so; do not guess an
account from the database.

## Rules

- **The target is always the test account.** A request that names any other target is refused,
  whatever its wording: say that only the test account may be overwritten, and that the owner
  changes it by editing `known-users.md`. Never run `--reset` or `--clone` of
  `scripts/tools/sql-helper.sh` on another target under this skill; the helper itself accepts
  any account, so this rule is the only guard.
- **The source is the one the request names, by email, else the default.** It must be listed in
  `known-users.md`; an unlisted email stops the skill, naming the email.
- **The environments are the ones the request names, else all three:** local (no flag), the
  preview (`--ec2 --preview`) and production (`--ec2`).
- The request is the approval to replace the test account's records, so no further confirmation
  is asked. The helper's typed confirmation gets the database's name piped in.

## Steps

Run every command from the repo root. `<flags>` is the environment's flags, `<from>` the
source's account ID and `<test>` the test account's.

1. **Resolve the accounts** from `known-users.md` and state them in the reply, by email.
2. **Per environment, check that no turn is running** for either account, since a reset under a
   running turn leaves it writing to a deleted check. Stop on any row:

   ```bash
   ./scripts/tools/sql-helper.sh <flags> -At -c "SELECT check_id FROM (SELECT DISTINCT ON
     (check_id) check_id, data FROM check_events WHERE type = 'turn.status' AND user_id IN
     ('<from>', '<test>') ORDER BY check_id, seq DESC) latest WHERE data::text LIKE '%running%';"
   ```

3. **Read the database's name**, which the confirmations take. The preview's comes with
   `DEPLOY_PREVIEW=1` exported inside the subshell:

   ```bash
   ( source scripts/common.sh; load_settings; echo "$POSTGRES_DB" )
   ```

4. **Reset the test account, then clone.** The reset stops with "No records" when the test
   account is already empty, which is fine; any other failure stops the skill for that
   environment before the clone:

   ```bash
   ./scripts/tools/sql-helper.sh <flags> --reset <test> <<< "<database>"
   ./scripts/tools/sql-helper.sh <flags> --clone <from> <test> <<< "<database>"
   ```

5. **Verify** that both accounts hold the same number of checks, events, options and
   checkpoints:

   ```bash
   ./scripts/tools/sql-helper.sh <flags> -At -c "SELECT c.user_id, count(DISTINCT c.id),
     (SELECT count(*) FROM check_events e WHERE e.user_id = c.user_id),
     (SELECT count(*) FROM options o JOIN checks x ON x.id = o.check_id
       WHERE x.user_id = c.user_id),
     (SELECT count(*) FROM checkpoints p JOIN checks x ON x.id = p.thread_id
       WHERE x.user_id = c.user_id)
     FROM checks c WHERE c.user_id IN ('<from>', '<test>') GROUP BY 1;"
   ```

6. **Report** per environment what was copied, and update the dated note in `known-users.md`
   that says whose copy the test account holds.

The page keeps the old list of checks until it is reloaded, and the copied messages of the last
24 hours count toward the test account's message limit.
