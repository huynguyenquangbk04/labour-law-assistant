export interface CritiqueResult {
  status: 'approved' | 'limit_reached' | 'failed'
  max_attempts: number
  reviews: { attempt: number; should_modify: boolean; feedback: string }[]
}

export function CritiqueDetails({ result }: { result?: CritiqueResult | null }) {
  if (!result) return null

  const labels = {
    approved: 'Critique passed — final answer',
    limit_reached: 'Attempt limit reached',
    failed: 'Critique incomplete',
  }

  return (
    <section aria-label="Critique review" className="mt-3 rounded-xl border bg-muted/30 p-3 text-sm text-foreground">
      <p role="status" className={`font-semibold ${result.status === 'approved' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-800 dark:text-amber-300'}`}>
        {labels[result.status]} · {result.reviews.length}/{result.max_attempts} reviews
      </p>
      {result.status === 'limit_reached' && (
        <p className="mt-1">Stopped after {result.max_attempts} answer attempts. The reviewer still requested changes.</p>
      )}
      {result.status === 'failed' && (
        <p className="mt-1">The review did not finish; this answer has not been confirmed.</p>
      )}
      <ol aria-label="Review notes" className="mt-2 space-y-2">
        {result.reviews.map(review => (
          <li key={review.attempt}>
            <p className="font-medium">Attempt {review.attempt} — {review.should_modify ? 'Revise' : 'Accepted'}</p>
            <p className="whitespace-pre-wrap">{review.feedback}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}
