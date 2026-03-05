// @ts-nocheck
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground shadow-md hover:bg-primary/80 transition-all hover:scale-105",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-all hover:scale-105",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground shadow-md hover:bg-destructive/80 transition-all hover:scale-105",
        outline: "text-foreground border-border bg-background/50 backdrop-blur-md",
        success: "border-transparent bg-success text-success-foreground shadow-md hover:bg-success/80 transition-all hover:scale-105",
        warning: "border-transparent bg-warning text-warning-foreground shadow-md hover:bg-warning/80 transition-all hover:scale-105",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
  VariantProps<typeof badgeVariants> { }

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
