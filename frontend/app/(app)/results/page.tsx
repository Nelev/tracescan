import { ResultsView } from "@/app/_components/results-view";
import results from "@/data/eval-results.json";
import { parseEvalRuns } from "@/lib/eval";

// The scores are a file in the repo (backend's `python -m eval.metrics` writes it), so the page
// is built with them: no backend call, and it reads the same on a deployed copy.
export default function ResultsPage() {
  return <ResultsView runs={parseEvalRuns(results)} />;
}
