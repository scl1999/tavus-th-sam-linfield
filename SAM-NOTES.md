# Sam's notes

## Why I chose this problem

When choosing what problem to target for this take-home challenge, I wanted to work on something Tavus could actually find useful and potentially take to an existing client in the real world. I think it is best to design functionality around a real customer's problem: they help shape and fund its development, and then you can take what you have learned to other potential customers.

I did not have access to customers or the opportunity to speak to them about their biggest pain points, so I started with my first-hand experience of technical interviews. I chose a Deloitte-style technical interview as a concrete example, not because I have validated this problem with Deloitte or agreed a solution with them.

My thought process when picking a problem to solve is:

1. How much of a problem is it? Is it a must-have or a nice-to-have? What is the total cost to the company if it remains unsolved?
2. Why hasn't it been solved yet?
3. What has changed in the underlying technology that makes it possible now, particularly in the last six months?
4. What competitive advantage do we have over others working in this space?
5. What is the return? Can we deliver a 10x improvement in cost, speed or another metric that matters to the customer? I see 10x as a useful startup ambition for building something customers want to snatch out of your hands, although it still needs to be measured.

## My thinking for this problem

1. **The problem and its cost.** Technical interviews take experienced engineers away from other work, while also requiring scheduling, coordination and a consistent candidate experience. Delays can slow hiring and potentially result in good candidates accepting another offer. The cost is not just the hour in the interview: it includes preparation, write-up and coordination. On the other hand, some engineers may be on the bench or enjoy interviewing, so not every interview hour is necessarily a lost billable hour. I do not have Deloitte's volumes, costs or conversion rates, so I cannot put a reliable dollar value on the problem yet. I would start by measuring those with a customer and finding out whether it is a must-have for them.

2. **Why hasn't it been solved?** There are already coding platforms, automated assessments and AI interview products. However, a coding test on its own is different from a face-to-face pair programming interview where the interviewer listens to the candidate's reasoning, understands the work in progress, knows when to stay quiet and asks a useful follow-up. Some existing experiences can feel clunky or lack that back-and-forth. Getting all of this to work reliably, fairly and naturally is hard.

3. **What has changed?** Real-time conversational video, speech, language models and tool calling can now be combined into an experience that was much harder to build previously. Tavus's CVI provides the video conversation, while tools let Charlie interact with the interview workspace. More recent work on conversation flow and real-time rendering points towards a much more natural experience. I would still need to test which improvements in the last six months make a measurable difference for this particular use case.

4. **Competitive advantage.** Tavus develops core parts of the conversational video stack and provides them through a platform developers can build on. That creates an opportunity to bring face-to-face interaction and the interview workspace together in one experience. I am also a big believer in working closely with enterprise customers and using forward deployed engineers to understand their workflows, similar to the approach taken by companies such as OpenAI and Anthropic. The advantage would need to be proven against alternatives on interview quality, reliability, cost and candidate experience, rather than assumed from the technology alone.

5. **Return.** The potential return is less engineer time spent on early-stage interviews, faster scheduling and more consistent coverage, while retaining an effective pair programming experience. For example, if a human normally spends 60-90 minutes per interview including preparation and notes, and an AI-supported process reduces that to nine minutes of review, that would be a 10x reduction in human time for that step. This is an illustration, not a result from this project: it excludes the cost of Tavus, infrastructure, quality assurance, failed sessions and any additional human review. The actual business case needs to measure total cost per completed interview, time to hire, interview quality and candidate experience against the existing process.

## Future work

Although I am pleased with what I have developed so far, there is still room for improvement. Here are the things I would work on next:

- **Improve Charlie's interview behaviour.** Run more live interviews and focus on giving candidates quiet thinking time, handling interruptions, asking relevant follow-up questions and noticing when what a candidate says does not match their code. Charlie should help the candidate make progress without giving away the answer. The current instructions are not a guarantee of compliance.
- **Make the interview more resilient.** Test real network drops, browser refreshes, device failures and Tavus outages during live sessions. Improve recovery and make it clear when work is saved, waiting to be saved or cannot be submitted after the cutoff. The existing automated outage checks are useful, but they do not replace live testing.
- **Review timing with real candidates.** Validate whether the stage timings and 55-minute technical cutoff give candidates enough time, including when there are accessibility needs or connection issues. Decide with the customer how extensions and interrupted interviews should be handled.
- **Join through existing video tools.** Explore Charlie joining Google Meet or similar calls, with a link shared in the call chat to the development environment. The candidate could enter an interview ID and password and use the workspace while speaking to Charlie in the video call. Tavus lists Google Meet and Zoom integration; connecting those calls to this application's authenticated workspace and interview state would still need to be built and tested.
- **Evaluate interviews after the fact.** Explore evaluator LLMs that review the transcript, submitted solutions, whiteboards and, where available and consented to, the relevant recording against a strict scoring rubric. The current recording is screen video only, so it is not a full recording of the interview. Build a golden evaluation set from past Deloitte interviews if the customer can provide appropriate, consented data and human-labelled outcomes. Use separate development and held-out test sets, measure agreement with trained human reviewers, per-criterion accuracy, precision and recall where appropriate, calibration and confidence intervals, and review errors and subgroup performance. Set acceptance thresholds with the customer before testing; overall accuracy alone could hide serious errors or unfair outcomes. Start with human review and an appeal or correction process rather than relying on an LLM to make hiring decisions.
- **Evaluate Charlie as well as the outcome.** Build repeatable scenarios for quiet working, thinking aloud, requests for answers and hints, clarification, skips, revisits, closing remarks and tool failures. Measure interruption rates, tool success, recovery and task completion, then supplement automated checks with real candidate and interviewer feedback. Test accents, speech patterns, assistive technology and other edge cases without assuming a particular way of speaking or working is less capable.
- **Explore proportionate anti-cheating measures.** First agree with the customer what risks actually matter and whether they can be addressed through question design, follow-up discussion and a later human interview. If additional measures are needed, make them transparent, accessible and subject to candidate consent and a human review process. Avoid treating a model's suspicion, a camera observation or a change in coding style as proof of cheating.
- **Improve privacy and operational readiness.** Agree consent, retention and deletion policies for interview data, restrict access, and review security, monitoring, incident response and recovery before use beyond a controlled demonstration. Validate the execution environment and deployment boundaries independently.
- **Expand and validate the question bank.** Add more self-contained coding and system design questions, check the starter code and examples, and have experienced interviewers review difficulty, clarity and relevance to the role. The current Run button executes candidate-written tests; it is not a grading system.

## Unknowns

- Are Deloitte engineers who conduct interviews on the bench, or are they losing time on active client projects? What does that time actually cost?
- Do engineers enjoy doing technical interviews and getting a break from client projects, or do they see them as a distraction? Would they prefer to stay involved in some stages?
- Do candidates dislike an AI interviewer and prefer a real human? This needs candidate feedback and, where possible, a choice between human and AI interviewers. I personally would prefer an AI interviewer because it feels like there is less pressure and I can be more myself, but that is my preference and may not be shared by others.
- Would a candidate trust the process and understand how their work is used, who reviews it and how to raise a concern?
- Can Charlie evaluate the process of solving a problem as usefully as an experienced human interviewer, including when the candidate takes an unusual but valid approach?
- How much human review is actually needed to maintain quality and fairness? Would that still leave enough of a time and cost saving to make the product worthwhile?
- What interview volume, scheduling delays and cost per interview would justify adoption? Who would own the budget and decision?
- How consistent are outcomes across roles, question difficulty, language backgrounds, disabilities and different communication styles? What accommodations would candidates need?
- What data can the customer legally and practically provide for evaluation, and what consent, security and retention requirements apply?
- How often do technical failures, interruptions or misunderstood requests occur in real interviews, and what fallback would make the experience acceptable?
