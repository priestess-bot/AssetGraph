import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import { ChevronRight, SlidersHorizontal, X } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return <header className="product-page-header">
    <div>{eyebrow ? <span>{eyebrow}</span> : null}<h1>{title}</h1>{description ? <p>{description}</p> : null}</div>
    {actions ? <div className="product-page-actions">{actions}</div> : null}
  </header>;
}

export function Breadcrumbs({ items }: { items: Array<{ label: string; href?: string }> }) {
  return <nav className="product-breadcrumbs" aria-label="当前位置">{items.map((item, index) => <span key={`${item.label}:${index}`}>{index ? <ChevronRight size={14} aria-hidden="true" /> : null}{item.href ? <a href={item.href}>{item.label}</a> : <strong>{item.label}</strong>}</span>)}</nav>;
}

export function SegmentedTabs({ value, onValueChange, items, children }: {
  value: string;
  onValueChange: (value: string) => void;
  items: Array<{ value: string; label: string; count?: number }>;
  children?: ReactNode;
}) {
  return <Tabs.Root className="product-tabs" value={value} onValueChange={onValueChange}>
    <Tabs.List aria-label="工作区视图">{items.map((item) => <Tabs.Trigger key={item.value} value={item.value}>{item.label}{item.count !== undefined ? <span>{item.count}</span> : null}</Tabs.Trigger>)}</Tabs.List>
    {children}
  </Tabs.Root>;
}

export function Inspector({ open, title, description, onClose, children }: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return <Dialog.Root open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="product-dialog-overlay" />
      <Dialog.Content className="product-inspector">
        <header><div><Dialog.Title>{title}</Dialog.Title>{description ? <Dialog.Description>{description}</Dialog.Description> : null}</div><Dialog.Close className="product-icon-button" title="关闭"><X size={18} aria-hidden="true" /></Dialog.Close></header>
        <div className="product-inspector-body">{children}</div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}

export function IconButton({ label, children, onClick, pressed }: {
  label: string;
  children: ReactNode;
  onClick?: () => void;
  pressed?: boolean;
}) {
  return <Tooltip.Provider delayDuration={350}><Tooltip.Root><Tooltip.Trigger asChild><button className="product-icon-button" type="button" aria-label={label} aria-pressed={pressed} onClick={onClick}>{children}</button></Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="product-tooltip" sideOffset={6}>{label}</Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>;
}

export function FilterButton({ count = 0, onClick }: { count?: number; onClick?: () => void }) {
  return <button className="product-secondary-button" type="button" onClick={onClick}><SlidersHorizontal size={16} aria-hidden="true" />筛选{count ? <span>{count}</span> : null}</button>;
}

export function ProgressSteps({ current, items }: { current: number; items: string[] }) {
  return <ol className="product-steps">{items.map((item, index) => <li key={item} className={index < current ? "complete" : index === current ? "active" : undefined}><span>{index < current ? "✓" : index + 1}</span><strong>{item}</strong></li>)}</ol>;
}
