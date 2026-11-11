import { HelpCircle } from "lucide-react";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Checkbox } from "./ui/checkbox";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

type SelectableToggleProps = {
  onSelect: (isSelected: boolean) => void;
  isSelected?: boolean;
  title: string;
  description?: string;
  buttonClass: string;
  checkClass: string;
};

const SelectableToggle = ({
  onSelect,
  isSelected = false,
  title,
  description,
  buttonClass,
  checkClass,
}: SelectableToggleProps) => {
  const handleClick = () => {
    onSelect(!isSelected);
  };

  return (
    <div className="relative inline-block">
      <Button
        variant="ghost"
        size="default"
        aria-pressed={isSelected}
        onClick={handleClick}
        className={cn(
          "duration-200",
          isSelected
            ? `${buttonClass} text-white shadow-2xs border-transparent`
            : "bg-muted text-muted-foreground hover:bg-neutral-200 dark:hover:bg-neutral-700",
        )}
      >
        <div className="flex items-center gap-2 text-muted-foreground">
          <Checkbox
            checked={isSelected}
            tabIndex={-1}
            className={cn(
              "pointer-events-none h-4 w-4 rounded-md transition-all duration-200",
              isSelected
                ? `${checkClass}`
                : "bg-white dark:bg-neutral-800 border-neutral-300 dark:border-neutral-600",
            )}
          />

          <span
            className={cn(
              "text-sm font-medium whitespace-nowrap",
              isSelected && "text-green-800 dark:text-foreground",
            )}
          >
            {title}
          </span>

          {/* Help icon for description */}
          {description && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <span className="inline-flex cursor-help transition-opacity hover:text-foreground" />
                }
              >
                <HelpCircle size={12} />
              </TooltipTrigger>
              <TooltipContent>{description}</TooltipContent>
            </Tooltip>
          )}
        </div>
      </Button>
    </div>
  );
};

export default SelectableToggle;
