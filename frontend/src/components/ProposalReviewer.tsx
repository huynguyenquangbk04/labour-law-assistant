import { useState, useEffect } from 'react'
import { CheckCircle2, XCircle, AlertTriangle, ArrowRight, Loader2, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import client from '../api/client'

interface Proposal {
  id: string
  status: string
  created_at: string
  source_filename: string
  proposal_type: string
  new_entity_id: string
  existing_entity_id: string
  reason: string
  suggested_tags: {
    old_node?: Record<string, string>
    new_node?: Record<string, string>
  }
  resolved_at?: string
}

interface ProposalReviewerProps {
  onUpdate?: () => void
}

const TYPE_COLORS: Record<string, string> = {
  REPLACES: 'text-red-600 bg-red-50 border-red-200',
  MODIFIES: 'text-amber-600 bg-amber-50 border-amber-200',
  SUPPLEMENTS: 'text-blue-600 bg-blue-50 border-blue-200',
  OVERLAPS: 'text-purple-600 bg-purple-50 border-purple-200',
}

const TYPE_ICONS: Record<string, string> = {
  REPLACES: '🔄',
  MODIFIES: '✏️',
  SUPPLEMENTS: '➕',
  OVERLAPS: '⚠️',
}

export default function ProposalReviewer({ onUpdate }: ProposalReviewerProps) {
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'pending' | 'all'>('pending')

  const fetchProposals = async () => {
    try {
      setLoading(true)
      const params = filter === 'pending' ? { status: 'pending' } : {}
      const response = await client.get('/proposals', { params })
      setProposals(response.data)
    } catch (error) {
      console.error('Failed to fetch proposals:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProposals()
  }, [filter])

  const handleAction = async (id: string, action: 'approve' | 'reject') => {
    setActionLoading(id)
    try {
      await client.post(`/proposals/${id}/${action}`)
      await fetchProposals()
      if (onUpdate) onUpdate()
    } catch (error) {
      console.error(`Failed to ${action} proposal:`, error)
    } finally {
      setActionLoading(null)
    }
  }

  const pendingCount = proposals.filter(p => p.status === 'pending').length

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground py-4">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>Loading proposals...</span>
      </div>
    )
  }

  if (proposals.length === 0) {
    return (
      <div className="text-xs text-muted-foreground italic px-1 py-2">
        {filter === 'pending' ? 'No pending proposals.' : 'No proposals yet.'}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Header controls */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          <button
            onClick={() => setFilter('pending')}
            className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-colors ${
              filter === 'pending'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            Pending ({pendingCount})
          </button>
          <button
            onClick={() => setFilter('all')}
            className={`text-[10px] px-2 py-0.5 rounded-full font-medium transition-colors ${
              filter === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            All
          </button>
        </div>
        <button onClick={fetchProposals} className="p-1 hover:bg-muted rounded-full">
          <RefreshCw className="w-3 h-3 text-muted-foreground" />
        </button>
      </div>

      {/* Proposal cards */}
      {proposals.map((p) => {
        const isExpanded = expandedId === p.id
        const colorClass = TYPE_COLORS[p.proposal_type] || 'text-gray-600 bg-gray-50 border-gray-200'
        const icon = TYPE_ICONS[p.proposal_type] || '❓'

        return (
          <div
            key={p.id}
            className={`border rounded-lg overflow-hidden transition-all ${
              p.status === 'approved'
                ? 'opacity-60 border-emerald-200'
                : p.status === 'rejected'
                ? 'opacity-40 border-red-200'
                : 'border-border'
            }`}
          >
            {/* Collapsed header */}
            <button
              onClick={() => setExpandedId(isExpanded ? null : p.id)}
              className="w-full flex items-center gap-2 p-2.5 text-left hover:bg-muted/50 transition-colors"
            >
              <span className="text-sm">{icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${colorClass}`}>
                    {p.proposal_type}
                  </span>
                  {p.status !== 'pending' && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      p.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                    }`}>
                      {p.status}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-foreground mt-1 truncate">
                  <span className="font-medium">{p.new_entity_id}</span>
                  <ArrowRight className="w-3 h-3 inline mx-1 text-muted-foreground" />
                  <span className="font-medium">{p.existing_entity_id}</span>
                </p>
              </div>
              {isExpanded ? (
                <ChevronUp className="w-3 h-3 text-muted-foreground flex-shrink-0" />
              ) : (
                <ChevronDown className="w-3 h-3 text-muted-foreground flex-shrink-0" />
              )}
            </button>

            {/* Expanded details */}
            {isExpanded && (
              <div className="px-2.5 pb-2.5 space-y-2 border-t bg-muted/20">
                {/* Reason */}
                <div className="mt-2">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Lý do</p>
                  <p className="text-[11px] text-foreground mt-0.5">{p.reason}</p>
                </div>

                {/* Source file */}
                <div>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Nguồn</p>
                  <p className="text-[11px] text-foreground mt-0.5">{p.source_filename}</p>
                </div>

                {/* Suggested tags */}
                {p.suggested_tags && Object.keys(p.suggested_tags).length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      Thay đổi đề xuất
                    </p>
                    <div className="mt-1 space-y-1">
                      {p.suggested_tags.old_node && Object.keys(p.suggested_tags.old_node).length > 0 && (
                        <div className="text-[10px] bg-red-50 dark:bg-red-950/30 border border-red-100 dark:border-red-900 rounded p-1.5">
                          <span className="font-bold text-red-700 dark:text-red-400">Node cũ:</span>{' '}
                          {Object.entries(p.suggested_tags.old_node).map(([k, v]) => (
                            <span key={k} className="inline-block mr-1.5">
                              <span className="text-muted-foreground">{k}=</span>
                              <span className="font-mono text-red-600 dark:text-red-400">{v}</span>
                            </span>
                          ))}
                        </div>
                      )}
                      {p.suggested_tags.new_node && Object.keys(p.suggested_tags.new_node).length > 0 && (
                        <div className="text-[10px] bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-100 dark:border-emerald-900 rounded p-1.5">
                          <span className="font-bold text-emerald-700 dark:text-emerald-400">Node mới:</span>{' '}
                          {Object.entries(p.suggested_tags.new_node).map(([k, v]) => (
                            <span key={k} className="inline-block mr-1.5">
                              <span className="text-muted-foreground">{k}=</span>
                              <span className="font-mono text-emerald-600 dark:text-emerald-400">{v}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Action buttons */}
                {p.status === 'pending' && (
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => handleAction(p.id, 'approve')}
                      disabled={actionLoading === p.id}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-emerald-600 text-white rounded-md text-[11px] font-bold hover:bg-emerald-700 transition-colors disabled:opacity-50"
                    >
                      {actionLoading === p.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3 h-3" />
                      )}
                      Approve
                    </button>
                    <button
                      onClick={() => handleAction(p.id, 'reject')}
                      disabled={actionLoading === p.id}
                      className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-red-600 text-white rounded-md text-[11px] font-bold hover:bg-red-700 transition-colors disabled:opacity-50"
                    >
                      <XCircle className="w-3 h-3" />
                      Reject
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
