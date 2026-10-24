import * as React from "react"
import { cn } from "../../lib/utils"

interface SpinnerProps extends React.SVGProps<SVGSVGElement> {
  size?: number
}

/** 纯装饰性加载指示器：语义信息由外层按钮的 aria-busy / 文案承担。 */
export function Spinner({ size = 14, className, ...props }: SpinnerProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("animate-spin shrink-0", className)}
      {...props}
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
