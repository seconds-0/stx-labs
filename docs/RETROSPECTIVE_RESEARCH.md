# Process Retrospective Research: Comprehensive Findings

**Research Date:** 2025-11-08  
**Focus:** Automated retrospective systems for AI agents analyzing HOW work was done, not WHAT was produced  
**Goal:** Build self-learning retrospective skill that prevents process mistakes from recurring

---

## Executive Summary

This research synthesizes best practices from:
- **Agile Retrospectives** (Start/Stop/Continue, 4Ls, Sailboat, Rose/Bud/Thorn, Mad/Sad/Glad)
- **SRE Post-Mortems** (Google, PagerDuty, Etsy blameless frameworks)
- **AI Agent Self-Assessment** (confidence calibration, transcript analysis, efficiency metrics)
- **Process Improvement** (Lean waste detection, technical debt metrics, rework measurement)
- **Automation Safety** (safe vs risky classification, approval workflows, staged rollouts)

**Key Innovation:** Hybrid retrospective system that ALWAYS analyzes but only reports when issues found, with tiered auto-apply vs approval-required recommendations.

---

## 1. Retrospective Template for Process Review

### 1.1 Agile-Inspired Process Frameworks

#### **Start/Stop/Continue** (Simplest - Good for Quick Analysis)
- **START:** What process improvements should we adopt?
- **STOP:** What inefficient patterns should we eliminate?
- **CONTINUE:** What worked well that we should preserve?

**Strengths:** Fast, actionable, easy to parse from transcripts  
**Weaknesses:** Less emotional awareness, can miss nuanced issues

#### **Four Ls** (Best for Learning & Sentiment Balance)
- **LOVED:** What process elements worked exceptionally well?
- **LOATHED:** What was frustrating, wasteful, or counterproductive?
- **LEARNED:** What new insights emerged about how to work better?
- **LONGED FOR:** What capabilities or workflows are missing?

**Strengths:** Balances objective and subjective, captures learning explicitly  
**Weaknesses:** Requires more nuanced analysis to categorize findings

#### **Rose/Bud/Thorn** (Good for Growth Mindset)
- **ROSE:** Successes and highlights in the process
- **THORN:** Challenges, pain points, inefficiencies
- **BUD:** Opportunities for future improvement

**Strengths:** Forward-looking, encourages innovation  
**Weaknesses:** May downplay serious problems as "growth opportunities"

#### **Sailboat Metaphor** (Visual - Good for Goal-Oriented Tasks)
- **WIND:** What helped us move forward?
- **ANCHORS:** What slowed us down or blocked progress?
- **ROCKS:** What risks or hazards did we face?
- **LAND:** Did we reach our goal? How close?

**Strengths:** Great for visualizing progress toward goal  
**Weaknesses:** Metaphor may not fit all task types

#### **Mad/Sad/Glad** (Emotional Intelligence Focus)
- **MAD:** What was frustrating or anger-inducing?
- **SAD:** What was disappointing or concerning?
- **GLAD:** What was positive or successful?

**Strengths:** Captures emotional impact, improves well-being  
**Weaknesses:** Risk of dwelling on negatives without actionable insights

### 1.2 SRE Post-Mortem Framework (Best for Deep Analysis)

Based on Google SRE, PagerDuty, and Etsy practices:

**Template Structure:**
1. **Incident Summary**
   - What task was being performed?
   - What was the intended outcome?
   - What actually happened?
   
2. **Impact Assessment**
   - Time wasted (iteration count × avg time per iteration)
   - Token efficiency loss (unnecessary reads, verbose outputs)
   - User frustration level (correction count, explicit feedback)
   - Confidence vs accuracy gap (stated confidence vs actual correctness)

3. **Timeline Analysis**
   - Key decision points in transcript
   - Tool invocations and their outcomes
   - Where did process deviate from protocol?
   - When did backtracking or rework occur?

4. **Contributing Factors** (NOT Root Cause - Systems Thinking)
   - **Immediate trigger:** What specific event initiated the problem?
   - **Latent conditions:** What systemic factors made this possible?
   - **Detection failure:** Why wasn't this caught earlier?
   - **Cognitive biases:** What thinking errors occurred?

5. **Systemic Analysis**
   - What in our PROCESS allowed this to happen?
   - Which protocols were violated or missing?
   - What assumptions proved incorrect?
   - What knowledge gaps existed?

6. **Action Items** (Tiered by Risk Level)
   - **MITIGATE (Auto-apply Safe):** Update documentation, add examples
   - **PREVENT (Auto-apply Medium):** Add checks to hooks, append to lists
   - **PROCESS (Approval Required):** Change hook logic, modify protocols
   - **OTHER (Approval Required):** Create new skills, major workflow changes

7. **Verification Plan**
   - How will we know these changes prevent recurrence?
   - What signals indicate the process is working?
   - What metrics track improvement?

**Key Principles from SRE:**
- **Blameless:** Assume good intentions, focus on systems not individuals
- **Use "what/how" questions:** Avoid "why" which invites defensiveness
- **Combat biases:** Fundamental attribution error, hindsight bias, confirmation bias, negativity bias
- **Seek outside perspectives:** Cross-check with documentation, examples, best practices

### 1.3 Recommended Hybrid Template for AI Agents

Combine SRE depth with Agile simplicity:

```markdown
# Process Retrospective: [Task Description]

## Quick Assessment (Four Ls Light)
- **Worked Well:** [1-2 key successes]
- **Friction Points:** [1-2 key pain points]
- **Learning:** [Key insight about process]
- **Missing:** [Key capability or knowledge gap]

## Efficiency Metrics
- **Iteration count:** [attempts to solution]
- **Rework rate:** [files edited multiple times, backtracking]
- **Token efficiency:** [unnecessary tool calls, verbose outputs]
- **Confidence calibration:** [stated confidence vs actual outcome]
- **Protocol adherence:** [% compliance with CLAUDE.md directives]

## Contributing Factors (If Issues Found)
1. **Immediate trigger:** [What started the problem?]
2. **Systemic enabler:** [What in process allowed it?]
3. **Detection gap:** [Why wasn't it caught earlier?]
4. **Knowledge gap:** [What wasn't known that should have been?]

## Actionable Improvements (Tiered)
### Auto-Apply (Safe)
- [ ] [Append example to CLAUDE.md section X]
- [ ] [Add FAQ entry]

### Propose for Approval (Medium Risk)
- [ ] [Modify hook configuration]
- [ ] [Update protocol checklist]

### Request Decision (High Risk)
- [ ] [Create new skill to capture workflow]
- [ ] [Change core directive in CLAUDE.md]

## Verification
- **Success signal:** [How to know it's working]
- **Metric to track:** [What to measure]
```

---

## 2. Analysis Checklist: What to Look For

### 2.1 Transcript Analysis Patterns

#### **Iteration & Backtracking Detection**
- [ ] Count of tool invocations per sub-goal (>3 suggests inefficiency)
- [ ] Repeated file reads of same file (cache miss or poor planning)
- [ ] Edit → Read → Edit cycles on same file (indicates trial-and-error)
- [ ] Tool failures followed by different tool (wrong tool selection)
- [ ] Apologies or corrections in transcript ("Sorry, I should have...")
- [ ] User corrections ("No, actually..." or "That's not quite right...")

#### **Protocol Violation Detection**
- [ ] Used Grep/Glob/Read directly instead of dispatching Explore agent
- [ ] Started coding without research when unfamiliar task
- [ ] Didn't check `bd ready` before starting (if .beads/ exists)
- [ ] Committed without user approval
- [ ] Didn't state confidence level before execution
- [ ] Skipped verification step after completion

#### **Cognitive Bias Indicators**
- [ ] **Overconfidence:** High confidence (9-10/10) followed by failure
- [ ] **Confirmation bias:** Only sought information supporting initial approach
- [ ] **Fundamental attribution error:** Blamed tool/API rather than checking own usage
- [ ] **Hindsight bias:** "Obviously I should have..." (wasn't obvious at the time)
- [ ] **Anchoring:** Stuck with first approach despite evidence for alternatives

#### **Communication Quality**
- [ ] Verbosity: Excessive explanation that doesn't add value
- [ ] Clarity: User needed to ask clarifying questions
- [ ] Completeness: Forgot to mention limitations or caveats
- [ ] Proactivity: Should have asked question but made assumption instead

### 2.2 Tool Usage Analysis

#### **Tool Selection Accuracy**
- [ ] First tool call succeeded (good selection)
- [ ] First tool call failed, switched to correct tool (poor heuristic)
- [ ] Multiple tool failures before success (knowledge gap)
- [ ] Used correct tool with wrong parameters (documentation gap)

#### **Tool Efficiency Patterns**
- [ ] Parallel tool calls when possible (good)
- [ ] Sequential calls that could have been parallel (inefficient)
- [ ] Redundant tool calls (reading same file twice)
- [ ] Missing tool calls (should have read file before editing)

#### **Research Quality** (for tasks using research skill)
- [ ] Appropriate thoroughness level chosen (quick/medium/very thorough)
- [ ] Sufficient agents dispatched initially
- [ ] Gap analysis performed (Phase 3.5)
- [ ] Follow-up research when confidence < 8/10
- [ ] Confidence level stated before execution

### 2.3 Hook History Analysis

**Pre-commit hooks:**
- [ ] Were hooks triggered as expected?
- [ ] Did hooks catch issues that should have been caught earlier?
- [ ] Were hook warnings ignored or addressed?
- [ ] Should new hook checks be added based on this task?

**Pre-execution hooks:**
- [ ] Did validation hooks run?
- [ ] Were errors caught before costly operations?
- [ ] Should new pre-flight checks be added?

### 2.4 Git Diff Analysis

#### **Code Quality Signals**
- [ ] Clean, incremental commits (good)
- [ ] Large, sprawling commits with unrelated changes (poor planning)
- [ ] Reverted changes (trial-and-error approach)
- [ ] Multiple edits to same lines (rework/churn)

#### **Documentation Updates**
- [ ] Documentation updated alongside code changes
- [ ] Examples added when new patterns introduced
- [ ] CLAUDE.md updated with new learnings

#### **Test Coverage**
- [ ] Tests added for new functionality
- [ ] Tests updated for changed behavior
- [ ] Regression tests for bugs fixed

---

## 3. Process Quality Metrics (Quantitative)

### 3.1 Efficiency Metrics

#### **Iteration Count (Lower = Better)**
- **Definition:** Number of attempts to reach acceptable solution
- **Measurement:** Count of major approach changes in transcript
- **Targets:**
  - Simple tasks: 1 iteration (ideal)
  - Medium tasks: 1-2 iterations
  - Complex tasks: 2-3 iterations
  - **>4 iterations = Process issue**

#### **Rework Rate (Lower = Better)**
- **Definition:** Percentage of work that had to be redone
- **Measurement:** 
  - File churn: Files edited multiple times / Total files edited
  - Line churn: Lines changed >1 time / Total lines changed
  - Revert rate: Commits reverted / Total commits
- **Targets:**
  - File churn: <20% acceptable, <10% good
  - **>30% = Significant process issue**

#### **Token Efficiency (Higher = Better)**
- **Definition:** Value delivered per token consumed
- **Measurement:**
  - Unnecessary file reads (reading same file >2 times)
  - Verbose outputs (>500 chars with no new information)
  - Redundant tool calls (same call with same params)
- **Targets:**
  - Zero redundant reads (cache hit ratio)
  - <10% verbose responses
  - **>20% waste = Optimization needed**

#### **Time to Diagnosis (Lower = Better)**
- **Definition:** For debugging tasks, time to identify root cause
- **Measurement:** Timestamp of task start → timestamp of correct diagnosis
- **Patterns:**
  - Immediate (<2 mins): Familiar issue, good pattern matching
  - Quick (2-5 mins): Effective research/exploration
  - Slow (>10 mins): Knowledge gap or poor search strategy
  - **>20 mins = Process improvement needed**

### 3.2 Quality Metrics

#### **Confidence Calibration (Closer to 1.0 = Better)**
- **Definition:** Alignment between stated confidence and actual success
- **Measurement:**
  - Expected Calibration Error (ECE): |stated_confidence - success_rate|
  - Track per confidence band (e.g., 8/10 tasks should succeed 80% of time)
- **Targets:**
  - ECE < 0.1: Well-calibrated
  - ECE 0.1-0.2: Acceptable
  - **ECE > 0.2: Systematic over/under-confidence**

#### **First-Time Success Rate (Higher = Better)**
- **Definition:** Percentage of tasks completed correctly on first attempt
- **Measurement:** Tasks with 1 iteration / Total tasks
- **Targets:**
  - Simple tasks: >90%
  - Medium tasks: >70%
  - Complex tasks: >50%
  - **<50% overall = Process/knowledge gaps**

#### **Protocol Adherence (Higher = Better)**
- **Definition:** Compliance with CLAUDE.md directives
- **Measurement:** 
  - Count mandatory protocols (e.g., "MUST dispatch Explore agent for searches")
  - Track violations per task
- **Targets:**
  - Critical protocols: 100% compliance
  - Standard protocols: >95% compliance
  - **<90% = Review protocol clarity or enforcement**

#### **User Correction Rate (Lower = Better)**
- **Definition:** How often user had to correct agent's understanding or approach
- **Measurement:** User messages containing corrections / Total user messages
- **Patterns:**
  - "No, actually..."
  - "That's not quite right..."
  - "I meant..."
  - Explicit disagreement or redirection
- **Targets:**
  - <5% correction rate: Good understanding
  - 5-10%: Acceptable
  - **>10% = Communication or comprehension issues**

### 3.3 Lean Waste Metrics

Based on Lean Software Development's 7 wastes (adapted for AI agents):

#### **1. Waiting**
- **Measurement:** Sequential operations that could be parallel
- **Example:** Reading files one at a time instead of parallel reads
- **Target:** <5% of operations waiting unnecessarily

#### **2. Over-processing**
- **Measurement:** Verbose outputs, excessive explanation, redundant analysis
- **Example:** 500-word explanation when 50 words suffices
- **Target:** <10% of output is redundant

#### **3. Defects**
- **Measurement:** Errors requiring rework (failed tests, incorrect outputs)
- **Example:** Code that doesn't run, wrong file edited
- **Target:** <5% defect rate

#### **4. Motion**
- **Measurement:** Context switching, unnecessary tool invocations
- **Example:** Switching between Grep/Glob when single Explore agent would work
- **Target:** <3 tool switches per task

#### **5. Over-production**
- **Measurement:** Creating outputs not requested by user
- **Example:** Building features user didn't ask for, excessive documentation
- **Target:** Zero over-production

#### **6. Transportation**
- **Measurement:** Moving data between tools unnecessarily
- **Example:** Reading file → extract info → read same file again
- **Target:** <2 file reads per unique file

#### **7. Inventory**
- **Measurement:** Started tasks not completed, partial work
- **Example:** Multiple TODO items created but not addressed
- **Target:** Complete tasks before starting new ones

---

## 4. Risk Classification: Safe vs Risky Auto-Apply

### 4.1 Classification Framework

Based on software deployment safety research and automation best practices:

#### **SAFE - Auto-Apply Without Approval**

**Characteristics:**
- **Append-only:** Adding to lists, adding examples, adding new sections
- **Documentation:** Updating docs, fixing typos, adding clarifications
- **Reversible:** Changes that can be easily undone
- **Isolated:** Affects single, non-critical section
- **Low blast radius:** If wrong, minimal impact

**Examples:**
- ✅ Add anti-pattern example to CLAUDE.md FAQ section
- ✅ Append to "Common mistakes" list
- ✅ Add code example to documentation
- ✅ Fix typo in CLAUDE.md
- ✅ Add new entry to decision log
- ✅ Update timestamp in cache config

**Safety Checks Before Auto-Apply:**
1. Is this append-only or modification?
2. If modification, is original content preserved?
3. Can this be reverted in <1 minute?
4. Does this affect critical paths (hooks, core directives)?
5. Is blast radius limited to documentation?

**If all checks pass → Auto-apply + Notify user**

#### **MEDIUM - Propose for Approval**

**Characteristics:**
- **Modification:** Changing existing content, reordering
- **Configuration:** Updating settings, thresholds, parameters
- **Moderate risk:** Could cause confusion if wrong
- **Testable:** Can validate before committing
- **Moderate blast radius:** Affects workflow but not catastrophically

**Examples:**
- ⚠️ Modify hook configuration (change threshold)
- ⚠️ Update protocol checklist (reorder steps)
- ⚠️ Change default thoroughness level (medium → very thorough)
- ⚠️ Adjust retry configuration
- ⚠️ Modify caching TTL values

**Approval Workflow:**
1. Present proposed change with clear diff
2. Explain reasoning (what problem does this solve?)
3. Show expected impact (what will change?)
4. Request explicit approval
5. After approval → Apply + Verify + Report

#### **HIGH RISK - Request Decision**

**Characteristics:**
- **Structural:** Adding/removing core directives, changing fundamental workflows
- **Logic changes:** Modifying hook logic, changing decision trees
- **Skill creation:** Capturing new repeatable process
- **High blast radius:** Could significantly alter agent behavior
- **Complex validation:** Hard to test comprehensively

**Examples:**
- 🚨 Create new skill to capture workflow
- 🚨 Add new MANDATORY directive to CLAUDE.md
- 🚨 Change hook execution logic
- 🚨 Remove existing protocol
- 🚨 Modify core research workflow
- 🚨 Change commit message requirements

**Decision Request Workflow:**
1. Present detailed analysis of problem
2. Propose solution with alternatives
3. Explain risks and benefits of each option
4. Provide recommendation with confidence level
5. Wait for user decision before proceeding
6. After decision → Implement + Validate + Document

### 4.2 Decision Tree for Classification

```
START
  ↓
Is this append-only? ────YES──→ Is it documentation? ────YES──→ SAFE
  ↓ NO                                  ↓ NO
  ↓                                     ↓
  ↓                              Does it add code/config example?
  ↓                                     ↓ YES → SAFE
  ↓                                     ↓ NO → MEDIUM
  ↓
Does it modify existing content?
  ↓ YES
  ↓
Is it core directive (MUST/NEVER/ALWAYS)? ───YES──→ HIGH RISK
  ↓ NO
  ↓
Is it hook logic or skill creation? ───YES──→ HIGH RISK
  ↓ NO
  ↓
Is it configuration/threshold? ───YES──→ MEDIUM
  ↓ NO
  ↓
Is it easily reversible (<1 min)? ───YES──→ MEDIUM
  ↓ NO
  ↓
HIGH RISK
```

### 4.3 Staged Rollout for Medium/High Risk Changes

**For MEDIUM Risk Changes:**
1. **Test in isolation:** Apply to test copy, validate
2. **User approval:** Show diff, get explicit OK
3. **Apply:** Make change
4. **Verify:** Check that behavior matches expected
5. **Monitor:** Track for next 3 tasks, watch for issues

**For HIGH RISK Changes:**
1. **Detailed proposal:** Full analysis, alternatives, recommendation
2. **User decision:** Wait for explicit approval
3. **Test thoroughly:** Validate in safe environment if possible
4. **Apply with rollback plan:** Make change, document how to revert
5. **Monitor closely:** Watch next 5+ tasks for unintended consequences
6. **Iterate:** Adjust based on real-world performance

**Rollback Triggers:**
- User explicitly requests rollback
- Degraded performance on objective metrics (>20% drop)
- Increased error rate (>10% increase)
- User frustration indicators (correction rate doubles)

---

## 5. Real Examples from Research

### 5.1 Google SRE Post-Mortem Example

**Incident:** Shakespeare search service outage

**Contributing Factors:**
1. **Trigger:** 88x traffic surge from Reddit post to /r/shakespeare
2. **Latent defect:** File descriptor leak when search term not in corpus
3. **Novel condition:** Newly discovered sonnet with word never in Shakespeare's works

**Key Insight:** "Under normal circumstances, the rate of task failures due to resource leaks is low enough to be unnoticed."

**Action Items (Categorized):**
- **Mitigate:** Update cascading failure response procedures
- **Prevent:** Plug file descriptor leak, add load shedding
- **Process:** Schedule failure scenario testing
- **Other:** Production freeze until error budget recovery

**Takeaway for AI Agents:**
- Don't just fix the immediate bug (file descriptor leak)
- Update procedures (mitigate)
- Add safeguards (load shedding)
- Improve testing (scenario testing)
- Learn from near-misses (low rate of failures was warning sign)

### 5.2 PagerDuty Blameless Post-Mortem Principles

**Core Principle:** "A blamelessly written postmortem assumes that everyone involved in an incident had good intentions and did the right thing with the information they had."

**Question Strategy:**
- ✅ "What did you think was happening?" (grounds in context)
- ✅ "What information did you have?" (reveals knowledge gaps)
- ✅ "What led to this decision?" (uncovers systemic factors)
- ❌ "Why did you do that?" (forces justification, invites blame)

**Bias Combat:**
1. **Fundamental Attribution Error:** Attributing to character vs circumstances
   - Example: "Agent is bad at research" vs "Research protocol was unclear"
2. **Hindsight Bias:** Everything seems obvious in retrospect
   - Example: "Obviously should have researched first" (but directive wasn't explicit)
3. **Confirmation Bias:** Seeking info that confirms blame
   - Example: Only looking at failures, ignoring successes with same approach
4. **Negativity Bias:** Overweighting negative events
   - Example: One failure overshadows 10 successes

**Restoration Techniques:**
- Reestablish mutual purpose: "Goal is to improve the system, not assign blame"
- Use contrasting: "I'm not saying X, I am saying Y"
- Invite outside perspective: "What would documentation say? What do examples show?"

**Takeaway for AI Agents:**
- Focus on systemic factors (missing protocols, unclear directives)
- Use "what/how" questions in analysis
- Assume past-me had good reasons (understand context)
- Combat biases explicitly in retrospective

### 5.3 Lean Waste Example: Rework in Software Development

**Concept:** "Rework is inevitable, but unchecked rework is waste."

**Measurement:** Information Loss Rate
- **Formula:** (Lines changed >1 time) / (Total lines changed)
- **Normalized:** Allows comparison across tasks, time periods
- **Interpretation:** Lower rate = more efficient process

**Actionable Insights:**
- Rework from new requirements: Expected (not waste)
- Rework from poor planning: Waste (preventable)
- Rework from unclear specs: Waste (ask clarifying questions earlier)

**Application to AI Agents:**
- Track file churn rate per task
- Identify patterns: Which file types get reworked most?
- Classify rework: Learning vs planning failure vs changing requirements
- Target reduction in planning-failure rework

### 5.4 Agile Retrospective: 4Ls in Practice

**Example from team retrospective:**

**LOVED:**
- New CI/CD pipeline caught bugs early
- Pair programming sessions improved code quality

**LOATHED:**
- Meeting overload reduced focus time
- Unclear acceptance criteria led to rework

**LEARNED:**
- Feature flags enable safer deployments
- Early user feedback prevents big pivots

**LONGED FOR:**
- Better test coverage for edge cases
- Automated performance testing

**Action Items:**
- START: Write acceptance criteria in tickets before sprint starts
- STOP: Scheduling meetings without clear agenda
- CONTINUE: Using feature flags for all new features
- ADD: Automated performance regression tests to CI pipeline

**Takeaway for AI Agents:**
- Categorize learnings into these 4 buckets
- Extract concrete actions (Start/Stop/Continue)
- Focus on process changes, not just outcomes

### 5.5 Confidence Calibration Example

**Research Finding:** "An LLM incorrectly responds with 'Geoffrey Hinton', assigning a 93% confidence score" (correct answer was "Michio Sugeno")

**ECE Measurement:** Expected Calibration Error using 0.1 bin size
- Example: For confidence 90-100%, if success rate is only 60%, ECE contribution = 0.3

**Patterns Identified:**
- Larger models (GPT-4o): Better overall calibration, but still overconfident on open-ended tasks
- Smaller models: Struggle with uncertainty estimation even with multiple-choice options
- All models: Inconsistent at low confidence (20-40%)

**Takeaway for AI Agents:**
- Track stated confidence vs actual outcome
- Calibrate over time (learn your own accuracy by confidence band)
- Flag tasks where confidence was >8/10 but outcome was failure
- Adjust confidence scoring based on task type (open-ended vs structured)

---

## 6. Recommendation Format

### 6.1 Structured Recommendation Output

```markdown
## Process Improvement Recommendation

### Context
**Task:** [Brief description]
**Issue:** [What process problem occurred?]
**Impact:** [How did this affect efficiency/quality?]

### Analysis
**Contributing Factors:**
1. [Systemic factor 1]
2. [Knowledge gap]
3. [Protocol violation or missing protocol]

**Evidence:**
- [Metric data: iteration count, rework rate, etc.]
- [Transcript excerpt showing issue]
- [Tool usage pattern demonstrating inefficiency]

### Proposed Changes

#### Tier 1: Auto-Applied (Safe)
✅ **Change 1:** [Description]
   - **Type:** Append to documentation
   - **File:** `CLAUDE.md` section X
   - **Content:** [Exact addition]
   - **Reasoning:** [Why this helps]
   - **Verification:** [How to confirm it's working]

#### Tier 2: Proposed for Approval (Medium Risk)
⚠️ **Change 2:** [Description]
   - **Type:** Modify configuration
   - **File:** [Hook config, skill file, etc.]
   - **Diff:** 
     ```diff
     - old value
     + new value
     ```
   - **Reasoning:** [Why this helps]
   - **Risk:** [What could go wrong]
   - **Mitigation:** [How to minimize risk]
   - **Verification:** [How to test]

**Request Approval:** Yes/No?

#### Tier 3: Request Decision (High Risk)
🚨 **Change 3:** [Description]
   - **Type:** Create new skill / Modify core directive
   - **Proposal:** [Detailed description]
   - **Alternatives:**
     1. [Option A: pros/cons]
     2. [Option B: pros/cons]
     3. [Option C: pros/cons]
   - **Recommendation:** [Which option and why]
   - **Confidence:** [X/10 with reasoning]
   - **Risks:** [Potential negative consequences]
   - **Benefits:** [Expected improvements]
   - **Rollback Plan:** [How to undo if needed]

**Request Decision:** Which option should I proceed with?

### Expected Outcomes
**Success Metrics:**
- [Metric 1: Target improvement]
- [Metric 2: Target improvement]

**Timeline:**
- Immediate: [Changes that take effect right away]
- Short-term (1-5 tasks): [What to monitor]
- Long-term (10+ tasks): [Trend to track]

### Verification Plan
- [ ] Apply changes
- [ ] Test on next similar task
- [ ] Measure metrics (iteration count, rework rate, etc.)
- [ ] Compare to baseline
- [ ] Adjust if needed
```

### 6.2 Notification Format (For Silent Retrospectives)

When analysis runs but finds no issues:

```markdown
✅ **Process Retrospective: No Issues Found**

**Task:** [Description]
**Metrics:**
- Iteration count: 1 (excellent)
- Rework rate: 0% (excellent)
- Confidence calibration: 0.05 ECE (well-calibrated)
- Protocol adherence: 100%

All process metrics within acceptable ranges. No improvements recommended.
```

When analysis finds issues and auto-applies safe fixes:

```markdown
⚙️ **Process Retrospective: Auto-Applied Improvements**

**Task:** [Description]
**Issues Found:**
- [Issue 1: Brief description]
- [Issue 2: Brief description]

**Auto-Applied Changes:**
1. ✅ Added anti-pattern example to CLAUDE.md section X
2. ✅ Updated FAQ with common mistake

**Changes Available for Review:**
- See `CLAUDE.md` (lines X-Y)
- Rollback with: `git diff HEAD~1 CLAUDE.md`

**Monitoring:**
- Will track [metric] for next 3 tasks
- Expected improvement: [Target]
```

When analysis requires user input:

```markdown
🔍 **Process Retrospective: Approval Needed**

**Task:** [Description]
**Issues Found:** [Summary]

**Proposed Changes:**
- [Tier 2 change requiring approval]
- [Tier 3 change requiring decision]

[Full recommendation format as above]

**Action Required:**
Please review and approve/reject proposed changes, or select from decision options.
```

---

## 7. Implementation Guidance

### 7.1 Session-Scoped Architecture

**Key Requirement:** No persistent database across sessions

**Approach:**
1. **In-memory tracking during session:**
   - Store task outcomes, metrics, transcripts in memory
   - Accumulate across tasks within single conversation
   
2. **Durable storage in git-tracked files:**
   - CLAUDE.md: Learnings, anti-patterns, protocols
   - Hook configs: Validation rules, pre-flight checks
   - Skills: Repeatable workflows captured as skills
   - Decision logs: ADR-style records in docs/ (optional)

3. **Retrospective triggering:**
   - **After every task completion** (hybrid mode)
   - Always analyze, only report if issues found
   - Store findings in conversation memory for synthesis

### 7.2 Analysis Workflow

```
TASK COMPLETE
    ↓
Collect Data:
  - Transcript of task
  - Tool invocations + outcomes
  - Hook execution history
  - Git diff (if applicable)
  - User corrections/feedback
    ↓
Run Analysis:
  - Calculate metrics (iteration count, rework rate, etc.)
  - Detect patterns (protocol violations, backtracking, etc.)
  - Check confidence calibration (if confidence was stated)
  - Identify waste (Lean 7 wastes)
    ↓
Classify Severity:
  - GREEN: All metrics in acceptable range → Silent pass (maybe just note in memory)
  - YELLOW: Minor issues, safe fixes available → Auto-apply + notify
  - RED: Significant issues, approval needed → Present recommendations
    ↓
Generate Recommendations:
  - Tier 1 (Safe): Auto-apply
  - Tier 2 (Medium): Propose for approval
  - Tier 3 (High): Request decision
    ↓
Apply Changes:
  - Tier 1: Apply immediately, notify user
  - Tier 2: Wait for approval, then apply
  - Tier 3: Wait for decision, then implement
    ↓
Verify:
  - Track metrics on next N tasks
  - Confirm improvement or adjust
    ↓
Update Memory:
  - Record learnings for session context
  - Inform future task approaches
```

### 7.3 Integration with Existing Workflows

**With research skill:**
- After research + execution, retrospective analyzes research quality
- Was thoroughness appropriate?
- Was gap analysis performed?
- Was confidence calibrated?

**With skill-maker:**
- Retrospective can recommend creating skill when:
  - Task succeeded well (good template to capture)
  - Task failed due to missing workflow (create workflow)
  
**With git workflow:**
- Retrospective analyzes commit quality
- Recommends commit message improvements
- Tracks code churn rates

**With bd (beads) issue tracking:**
- Retrospective can create beads for systemic issues
- Example: "Research workflow needs clarification" → create task bead
- Track resolution of process debt

### 7.4 Metrics Baseline Establishment

**First 10 tasks:** Establish baseline
- Track all metrics, don't flag issues yet
- Calculate baseline rates:
  - Avg iteration count by task complexity
  - Baseline rework rate
  - Baseline token efficiency
  - Confidence calibration by task type

**After baseline:** Compare to baseline
- Flag when >20% worse than baseline
- Recognize when >20% better (celebrate!)
- Adjust baseline quarterly (rolling average)

### 7.5 Avoiding Analysis Paralysis

**Key Principle:** Lightweight by default, deep dive on demand

**Default Mode (Hybrid):**
- Calculate key metrics (5-10 seconds)
- Quick pattern scan (protocol violations, obvious waste)
- If all green → Silent pass (store in memory, no output)
- If any yellow/red → Generate lightweight report

**Deep Dive Mode (User-Triggered):**
- User says "run full retrospective" or "analyze process"
- Comprehensive analysis of transcript, tools, git, hooks
- Detailed recommendations with full context
- Suitable for end-of-day or end-of-project reviews

**Frequency Tuning:**
- Start: After every task
- If too noisy: Only flag significant issues (RED only)
- If helpful: Keep current frequency
- User preference: Add config for "verbosity" (silent/normal/verbose)

---

## 8. Example Retrospectives

### 8.1 Example: Simple Task, No Issues

**Task:** "Rotate video 90 degrees clockwise"

**Transcript Summary:**
- Researched ffmpeg rotation syntax (2 Explore agents, quick)
- Executed ffmpeg command successfully
- Verified output
- Stated confidence: 9/10

**Metrics:**
- Iteration count: 1 ✅
- Rework rate: 0% ✅
- Token efficiency: High (no redundant calls) ✅
- Confidence calibration: 9/10 confidence, task succeeded ✅
- Protocol adherence: 100% (dispatched Explore agents as required) ✅

**Retrospective Output:**
```
✅ Process Retrospective: No Issues Found

Task completed efficiently with excellent metrics. No improvements needed.
```

*(Silent mode: Would just store in memory, no output)*

---

### 8.2 Example: Medium Task, Minor Inefficiency, Auto-Fix

**Task:** "Find all uses of deprecated API in codebase"

**Transcript Summary:**
- Used Grep directly instead of dispatching Explore agent
- Found 80% of uses
- User corrected: "You missed the imports in test files"
- Re-ran Grep with different glob pattern
- Found remaining 20%

**Metrics:**
- Iteration count: 2 (acceptable, but could be 1) ⚠️
- Rework rate: 0% ✅
- Token efficiency: Medium (redundant Grep calls) ⚠️
- Confidence calibration: 8/10 stated, but incomplete result ⚠️
- Protocol adherence: **VIOLATION** (used Grep directly) 🚨

**Analysis:**
- **Issue:** Protocol violation - CLAUDE.md says "MUST dispatch Explore agent for ALL information gathering"
- **Impact:** Incomplete result, required user correction, wasted iteration
- **Contributing Factor:** Directive exists but may not be salient enough

**Retrospective Output:**
```
⚙️ Process Retrospective: Auto-Applied Improvements

**Task:** Find all uses of deprecated API in codebase
**Issues Found:**
- Protocol violation: Used Grep directly instead of Explore agent
- Incomplete result required user correction
- Confidence 8/10 but result was incomplete (calibration gap)

**Auto-Applied Changes:**
✅ Added to CLAUDE.md FAQ:

---
Q: When searching codebase, can I use Grep directly for simple searches?
A: **NO.** ALWAYS dispatch Explore agent for ALL information gathering,
   including "simple" searches. Explore agents are more thorough and catch
   edge cases (like imports in test files) that direct Grep often misses.
   
   Example violation: Using Grep to find API uses → missed test file imports
   Correct approach: Dispatch Explore agent with objective "Find all uses of X,
   including imports, comments, and test files"
---

**Monitoring:**
- Will track Explore agent usage for next 5 search tasks
- Expected: 100% compliance with information gathering protocol

**Metrics:**
- Iteration count: 2 (target: 1 for this task type)
- Protocol adherence: 0% on this task (target: 100%)
```

---

### 8.3 Example: Complex Task, Significant Issues, Approval Needed

**Task:** "Build automated dashboard generation pipeline"

**Transcript Summary:**
- Started coding immediately without research
- Tried approach A (matplotlib) → too slow
- Tried approach B (seaborn) → didn't support interactivity
- Researched "best dashboard library python" mid-task
- Found Plotly, rewrote everything
- Spent 40 minutes total (should have been 15 with research-first)
- User mildly frustrated: "This is taking a while..."

**Metrics:**
- Iteration count: 3 (poor for this task) 🚨
- Rework rate: 67% (rewrote twice) 🚨
- Token efficiency: Low (read docs 3x for different libraries) 🚨
- Confidence calibration: Never stated confidence (protocol violation) ⚠️
- Protocol adherence: **CRITICAL VIOLATION** (skipped research-first) 🚨

**Analysis:**
- **Issue:** Violated "EXPLORE BEFORE EXPLOIT" principle
- **Impact:** 2.5x time waste, user frustration, massive rework
- **Contributing Factors:**
  1. Research-first directive not followed
  2. Research skill not invoked
  3. Overconfidence in Python dashboard knowledge
- **Systemic Enabler:** No pre-flight check to enforce research-first

**Retrospective Output:**
```
🔍 Process Retrospective: Approval Needed

**Task:** Build automated dashboard generation pipeline
**Issues Found:**
- CRITICAL: Skipped research-first workflow (CLAUDE.md violation)
- High rework rate (67% - rewrote code twice)
- Low token efficiency (read 3 different library docs)
- User frustration (explicit feedback: "This is taking a while")

**Impact Quantified:**
- Time wasted: ~25 minutes (40 actual vs 15 estimated with research)
- Rework: 2 full rewrites
- Token waste: 3x documentation reads

**Contributing Factors:**
1. Research-first directive exists but wasn't followed
2. No pre-flight check to enforce research for unfamiliar tasks
3. Overconfidence in existing knowledge (no research needed)

**Proposed Changes:**

### Tier 2: Proposed for Approval (Medium Risk)
⚠️ **Change 1: Add Pre-Flight Research Check**
   - **Type:** Create pre-commit hook or skill activation heuristic
   - **Proposal:** Before starting implementation on moderate/complex tasks,
     automatically check:
     - Is this task familiar (done in last month)?
     - Is confidence 100%?
     - If NO to either → Auto-suggest: "Should I research this first?"
   - **Reasoning:** Prevents research-skip pattern that led to 2.5x time waste
   - **Risk:** Might slow down truly simple tasks with unnecessary prompts
   - **Mitigation:** Only trigger for tasks estimated >5 min effort
   - **Verification:** Track pre-flight research suggestions vs outcomes

**Request Approval:** Should I add this pre-flight check? Yes/No?

### Tier 3: Request Decision (High Risk)
🚨 **Change 2: Strengthen Research-First Directive**
   - **Current:** "EXPLORE BEFORE EXPLOIT - Always research before diving in"
   - **Issue:** Not explicit enough, easy to skip
   - **Options:**

**Option A: Make MANDATORY (Recommended)**
```diff
- **EXPLORE BEFORE EXPLOIT** - Always research before diving in
+ **🚨 MANDATORY: RESEARCH BEFORE IMPLEMENTATION 🚨**
+ For ANY task with complexity ≥ medium OR confidence < 100%:
+ 1. STOP before writing code
+ 2. Dispatch Explore agents OR invoke research skill
+ 3. Achieve confidence ≥ 8/10 with evidence
+ 4. ONLY THEN proceed to implementation
+ 
+ VIOLATION CONSEQUENCES: High rework rates, time waste, user frustration
+ RECENT EXAMPLE: Dashboard task - skipped research → 67% rework, 2.5x time waste
```
   - **Pros:** Crystal clear, hard to miss, includes consequences
   - **Cons:** Very directive, reduces flexibility
   - **Confidence:** 9/10 this would have prevented this issue

**Option B: Add Checklist Instead**
```diff
+ ## Pre-Implementation Checklist
+ Before writing code, ask yourself:
+ - [ ] Have I researched best practices for this task?
+ - [ ] Do I have evidence-based confidence (≥8/10)?
+ - [ ] Have I explored alternatives?
+ - [ ] Is this a familiar task I've done recently?
+ 
+ If ANY of first 3 are "No" → Research first
+ If #4 is "Yes" → May proceed
```
   - **Pros:** Less prescriptive, encourages thinking
   - **Cons:** Easy to skip checklist, less enforcement
   - **Confidence:** 6/10 this would have prevented this issue

**Option C: Do Nothing, Rely on Learning**
   - **Pros:** Trust agent to learn from this mistake
   - **Cons:** No systematic prevention, likely to recur
   - **Confidence:** 3/10 this prevents future occurrences

**Recommendation:** Option A (Make MANDATORY)
**Reasoning:** 
- This is a pattern violation with clear, quantified impact
- Current directive is too easy to skip
- Option A makes it unmissable without being onerous
- Can always soften later if too rigid

**Request Decision:** Which option should I implement?
A (Mandatory), B (Checklist), C (Do Nothing), or Other (describe)?

### Expected Outcomes
**Success Metrics:**
- Research-first compliance: 0% → 100% (target)
- Rework rate: 67% → <20% (target)
- Time to completion: -40% (avoid false starts)

**Timeline:**
- Immediate: Add MANDATORY directive or checklist
- Short-term (next 5 tasks): Monitor compliance and rework rates
- Long-term (next 20 tasks): Confirm rework rate reduction sustained

**Verification Plan:**
- [ ] Implement approved changes
- [ ] Track research-first compliance on next 10 implementation tasks
- [ ] Measure rework rate comparison (baseline 30% → target <20%)
- [ ] Monitor user feedback (frustration indicators)
- [ ] Adjust directive clarity if violations continue
```

---

## 9. Key Takeaways for Implementation

### 9.1 Core Principles

1. **Blameless by Default**
   - Assume good intentions, focus on systems
   - Ask "what in the process allowed this?" not "why did I do this?"
   - Combat cognitive biases explicitly

2. **Quantify Impact**
   - Metrics make issues concrete (67% rework rate vs "lots of rework")
   - Compare to baselines and targets
   - Track trends over time

3. **Tiered Recommendations**
   - Safe = Auto-apply (documentation, append-only)
   - Medium = Propose (configuration, reversible)
   - High = Request decision (structural, logic changes)

4. **Hybrid Approach**
   - Always analyze, only report when issues found
   - Avoid notification fatigue
   - Deep dive on demand

5. **Session-Scoped**
   - No persistent DB across sessions
   - Durable storage in git-tracked files (CLAUDE.md, hooks, skills)
   - In-memory tracking within conversation

### 9.2 Critical Success Factors

1. **Lightweight by Default**
   - 5-10 second analysis per task
   - Silent pass when metrics are green
   - Don't create busywork

2. **Actionable Recommendations**
   - Every finding → Specific change proposal
   - Clear diff showing exact modification
   - Reasoning for why this helps

3. **Evidence-Based**
   - Root in transcript, tool calls, metrics
   - Avoid speculation
   - Cite specific examples

4. **Learn Over Time**
   - Establish baselines (first 10 tasks)
   - Track trends (rolling averages)
   - Adjust thresholds as performance improves

5. **User Control**
   - Approval required for risky changes
   - Rollback plans for all changes
   - User can tune sensitivity (verbose/normal/silent)

### 9.3 Common Pitfalls to Avoid

❌ **Analysis Paralysis:** Spending more time on retrospective than task took
✅ **Solution:** Lightweight default, deep dive on demand

❌ **Blame Language:** "I failed to..." or "I should have known..."
✅ **Solution:** Systemic language - "Process lacked..." or "Directive unclear..."

❌ **Vague Recommendations:** "Be better at research"
✅ **Solution:** Specific, actionable - "Add pre-flight research check"

❌ **Over-Automation:** Auto-applying risky changes without approval
✅ **Solution:** Strict tier classification, approval for medium/high risk

❌ **Noise:** Reporting every minor variation from ideal
✅ **Solution:** Thresholds (>20% worse than baseline), silent green

❌ **Static Baselines:** Comparing to fixed "ideal" that may not be realistic
✅ **Solution:** Rolling baselines, continuous recalibration

---

## 10. Next Steps for Implementation

### 10.1 Minimum Viable Retrospective (MVR)

**Phase 1: Basic Metrics Collection**
1. Implement in-memory tracking during session
2. Calculate core metrics after each task:
   - Iteration count
   - Protocol adherence (simple binary checks)
   - Confidence calibration (if stated)
3. Silent mode: Just track, don't report yet
4. Establish baseline over 10 tasks

**Phase 2: Detection & Notification**
1. Add threshold checks (>20% worse than baseline)
2. Report only when thresholds exceeded
3. Simple notification format (no recommendations yet)
4. Validate that detection is working

**Phase 3: Recommendations**
1. Add tier classification (safe/medium/high)
2. Generate recommendations for detected issues
3. Auto-apply safe fixes
4. Request approval for medium/high

**Phase 4: Verification & Learning**
1. Track whether recommendations actually improve metrics
2. Adjust thresholds based on effectiveness
3. Refine tier classification based on outcomes
4. Iterate on retrospective quality

### 10.2 Testing Strategy

**Unit Tests:**
- Metric calculation (iteration count, rework rate, etc.)
- Pattern detection (protocol violations, backtracking)
- Tier classification (safe/medium/high)
- Recommendation generation

**Integration Tests:**
- Run on historical task transcripts
- Verify correct issues detected
- Check recommendation quality
- Ensure no false positives

**Real-World Validation:**
- Deploy in silent mode first (10 tasks)
- Review retrospective outputs manually
- Tune thresholds and patterns
- Enable auto-apply for safe tier only initially
- Gradually expand to medium tier after validation

### 10.3 Documentation Needs

**For Users:**
- What retrospective does
- How to interpret findings
- How to approve/reject recommendations
- How to tune sensitivity

**For Developers/Claude:**
- Metric definitions
- Tier classification rules
- Pattern detection logic
- How to extend with new analyses

**Decision Log:**
- Why hybrid mode (vs always-on)?
- Why session-scoped (vs persistent DB)?
- Why tiered recommendations (vs all require approval)?
- Key design decisions with rationale

---

## 11. Research Sources Summary

### Academic & Industry Papers
- **AISI Work (2024):** Transcript analysis for AI agent evaluations
- **ArXiv (2025):** Confidence calibration in LLMs, overconfidence patterns
- **CHI Conference (2024-2025):** Human-AI collaboration, confidence effects

### SRE & Post-Mortem Frameworks
- **Google SRE Book:** Example postmortem, contributing factors analysis
- **PagerDuty:** Blameless postmortem culture, bias combat strategies
- **Etsy:** (Referenced as pioneer in blameless post-mortems)

### Agile & Retrospective Frameworks
- **Aha.io, Mural, Miro, Smartsheet:** Retrospective templates (2024-2025)
- **ScatterSpoke, Dezkr, RetroTeam:** Framework comparisons and best practices

### Software Process Improvement
- **Lean Manufacturing:** 7 wastes adapted for software development
- **Technical Debt Management:** Metrics, measurement, prioritization
- **Kede Hub:** Rework and waste measurement (information loss rate)

### Automation & Safety
- **LaunchDarkly, Microsoft, Google Cloud:** Safe deployment practices
- **Feature flags, staged rollouts, approval workflows**
- **Risk assessment automation, compliance workflows**

### Decision Records
- **Agile Alliance:** ADRs (Architecture Decision Records)
- **IcePanel:** Best practices for decision logging

---

## Conclusion

This research provides a comprehensive framework for building an automated retrospective skill for Claude Code that:

1. **Analyzes HOW work was done** using proven frameworks from Agile, SRE, and Lean
2. **Quantifies process quality** with specific, measurable metrics
3. **Detects patterns** automatically from transcripts, tools, hooks, and git
4. **Generates tiered recommendations** (safe auto-apply vs approval-required)
5. **Operates in hybrid mode** (always analyze, only report if issues found)
6. **Prevents recurrence** by updating CLAUDE.md, hooks, and skills
7. **Stays session-scoped** with durable storage in git-tracked files

**The core innovation** is combining blameless post-mortem culture (focus on systems, not blame) with Agile retrospective simplicity (actionable Start/Stop/Continue) and automated analysis (metrics, pattern detection, confidence calibration).

This enables continuous process improvement where every task makes the agent better at its job, without creating notification fatigue or analysis paralysis.
