# Coordination disclosures - 2026-11-04

1. Branch deletion (already reported to the user when it happened, recorded here
   for the durable record): branch live/reviewer-skip-guard was created
   erroneously at 027b1a35de40da381dc91190969af8075775755d (wrong base),
   deleted seconds later, and recreated from the correct base at
   d96e09d852eceac2191452844a038a5f1791a88a. No content was lost; the erroneous
   commit carried no unique work. Policy going forward: no branch deletion at
   all, even seconds-old; preflight ls-remote before any branch creation.

2. Attribution clarification: commits 6e5bd37 and 0c52bab on Research_lab were
   coordinator-authored evaluation work pushed via the owner Researcher token
   before the credential-routing correction (2026-11-04 ~15:26 EET). Routing
   since then: instinct-telkomsel = coordination commits only; role/model work
   = coolkowkank-bot with role-honest author labels; the owner coolkowkank
   token is used only for actual Researcher-role research/** publications and,
   per the owner's explicit grant (Slack message 1793799527.885349,
   2026-11-04 15:38 EET), Eva's Research_lab review publications. Eva reviews
   1-2 remain bot-published; no history rewrite.
