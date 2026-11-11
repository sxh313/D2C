import React from "react";

const Loading = () => (
  <div className="flex h-full w-full flex-col items-center justify-center p-6 text-center">
    {/* Code editor frame */}
    <div className="mb-5 w-full max-w-[260px] overflow-hidden rounded-lg border border-neutral-300 bg-white shadow-sm dark:border-neutral-700 dark:bg-neutral-800">
      {/* Title bar */}
      <div className="flex items-center gap-1.5 border-b border-neutral-200 px-3 py-2.5 dark:border-neutral-700">
        <div className="h-2 w-2 rounded-full bg-neutral-300 dark:bg-neutral-600" />
        <div className="h-2 w-2 rounded-full bg-neutral-300 dark:bg-neutral-600" />
        <div className="h-2 w-2 rounded-full bg-neutral-300 dark:bg-neutral-600" />
      </div>

      {/* Shimmer code lines */}
      <div className="flex flex-col gap-[10px] px-4 py-4">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div className="h-1.5 w-16 animate-pulse rounded-full bg-green-400/80" />
        </div>
        <div className="flex items-center gap-2 pl-4">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-24 animate-pulse rounded-full bg-neutral-400 dark:bg-neutral-500"
            style={{ animationDelay: "200ms" }}
          />
        </div>
        <div className="flex items-center gap-2 pl-4">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-20 animate-pulse rounded-full bg-neutral-400 dark:bg-neutral-500"
            style={{ animationDelay: "400ms" }}
          />
        </div>
        <div className="flex items-center gap-2 pl-8">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-28 animate-pulse rounded-full bg-neutral-300 dark:bg-neutral-600"
            style={{ animationDelay: "600ms" }}
          />
        </div>
        <div className="flex items-center gap-2 pl-8">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-16 animate-pulse rounded-full bg-neutral-300 dark:bg-neutral-600"
            style={{ animationDelay: "800ms" }}
          />
        </div>
        <div className="flex items-center gap-2 pl-4">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-12 animate-pulse rounded-full bg-neutral-400 dark:bg-neutral-500"
            style={{ animationDelay: "1000ms" }}
          />
        </div>
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-3 rounded-full bg-neutral-300 dark:bg-neutral-700" />
          <div
            className="h-1.5 w-10 animate-pulse rounded-full bg-green-400/80"
            style={{ animationDelay: "1200ms" }}
          />
        </div>
      </div>
    </div>

    {/* Text */}
    <p className="text-[15px] font-medium text-neutral-800 dark:text-neutral-200">
      Generating code...
    </p>
    <p className="mt-2 text-sm leading-5 text-neutral-600 dark:text-neutral-400">
      Images and complex layers take longer to process
    </p>
  </div>
);

export default Loading;
