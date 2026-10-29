import { createRoot } from "react-dom/client";
import { useRef, useState } from "react";
import { CodingWorkspace } from "../../src/components/CodingWorkspace";
import { TopBar } from "../../src/components/TopBar";
import { VideoStage } from "../../src/components/VideoStage";
import "../../src/styles.css";

// Deterministic visual fixture; no Tavus calls or media permission requests.
function Preview() {
  const [language, setLanguage] = useState<"python3" | "typescript">("python3");
  const [code, setCode] = useState("class Solution:\n    def removeDuplicates(self, nums: list[int]) -> int:\n        pass\n");
  const [terminal, setTerminal] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  return <div className="app">
    <TopBar elapsedSeconds={334} phase="coding_easy" frozen={false} remainingSeconds={566} listening={true}
      recordingLabel="" sharing={false} onShareScreen={() => undefined} onStopSharing={() => undefined} onLeave={() => undefined}/>
    <main className="stage dock-layout">
      <VideoStage videoRef={video} preview={null} docked={true} speaking={false} connecting={false} audioBlocked={false} onResumeAudio={() => undefined}/>
      <CodingWorkspace problem={{challenge_number:26, question_title:"Remove Duplicates from Sorted Array", difficulty_level:"Easy", question:"Given an integer array nums sorted in non-decreasing order, remove the duplicates in-place such that each unique element appears only once. The relative order of the elements should be kept the same.\n\nConsider the number of unique elements in nums to be k. After removing the duplicates, return k. The first k elements of nums should contain the unique elements in sorted order. The remaining elements beyond index k - 1 can be ignored. Example 1: Input: nums = [1,1,2] Output: 2, nums = [1,2,_] Explanation: Your function should return k = 2, with the first two elements of nums being 1 and 2 respectively. Example 2: Input: nums = [0,0,1,1,1,2,2,3,3,4] Output: 5, nums = [0,1,2,3,4,_,_,_,_,_] Constraints: 1 <= nums.length <= 3 * 10^4\n-100 <= nums[i] <= 100"}}
        language={language} code={code} terminal={terminal} frozen={false} running={false} onLanguage={setLanguage} onCode={setCode} onRun={() => setTerminal("Process exited with code 0.")}/>
    </main>
  </div>;
}
createRoot(document.getElementById("root")!).render(<Preview />);
