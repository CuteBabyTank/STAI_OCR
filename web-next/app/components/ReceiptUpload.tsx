"use client";
// The Receipts page's "Add receipts" dialog. It is now just a Modal around the
// shared capture UI in ReceiptCapture.tsx — the same components the /add page
// renders, so the two surfaces cannot drift.
//
// The staging list and the run itself live in lib/ocrJobs.tsx, above this modal
// in the tree, so pressing Run OCR and immediately closing this window does not
// abandon the read: the corner toast (components/OcrToast.tsx) reports the same
// run once the modal is gone, and reopening shows it still in progress.
import { useOcrJobs } from "../lib/ocrJobs";
import { Modal, Button } from "./ui";
import { CaptureChoices, CaptureQueue, RunOcrButton } from "./ReceiptCapture";

export default function ReceiptUpload({ onClose }: { onClose: () => void }) {
  const { counts, clearFinished } = useOcrJobs();
  const { done, reading } = counts;

  // Closing the window is the user acknowledging a finished run: its rows go
  // away so the next open starts clean, and the corner toast stops reporting
  // it. A run still in flight is untouched (clearFinished is a no-op then) —
  // the whole point is that closing does not cancel it.
  const closeModal = () => {
    clearFinished();
    onClose();
  };

  return (
    <Modal
      title="Add receipts"
      wide
      onClose={closeModal}
      footer={
        <>
          {/* Closing mid-read is a supported move, not an abandonment: the run
              belongs to the store and the corner toast takes over reporting. */}
          <Button onClick={closeModal}>
            {reading > 0 ? "Close — keep reading" : done ? "Done" : "Close"}
          </Button>
          <RunOcrButton />
        </>
      }
    >
      <CaptureChoices />
      <CaptureQueue />
    </Modal>
  );
}
