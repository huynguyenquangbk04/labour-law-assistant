import { useState } from 'react'
import { ChevronDown, ChevronUp, FileText, ExternalLink } from 'lucide-react'

interface Reference {
  id: string
  title?: string
  content: string
  source?: string
  distance?: number
}

export default function ReferenceCard({ reference }: { reference: Reference }) {
  const [isExpanded, setIsExpanded] = useState(false)

  return (
    <div className="border rounded-xl bg-card overflow-hidden transition-all hover:shadow-md mb-3">
      <div 
        className="p-4 flex items-center justify-between cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="p-1.5 bg-primary/5 rounded-md">
            <FileText className="w-4 h-4 text-primary" />
          </div>
          <span className="font-semibold text-sm">{reference.source || reference.id}</span>
          {reference.distance && (
            <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded-full font-mono">
              Score: {(1 - reference.distance).toFixed(3)}
            </span>
          )}
        </div>
        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </div>
      
      {isExpanded && (
        <div className="px-4 pb-4 pt-0">
          <div className="p-3 bg-muted rounded-lg text-sm text-foreground/80 leading-relaxed max-h-48 overflow-y-auto">
            {reference.content}
          </div>
          <div className="mt-3 flex justify-end">
            <button className="flex items-center gap-1.5 text-xs font-medium text-primary hover:underline">
              View Document <ExternalLink className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}