import TaskExtractor from "./components/TaskExtractor";
import UploadCard from "./components/UploadCard";

export default function App() {
  return (
    <div className="wrap">
      <h1>Meetings → Tasks Generator </h1>
      <TaskExtractor />
      <h2 style={{ marginTop: 24 }}>Upload & Index</h2>
      <UploadCard />
    </div>
  );
}
