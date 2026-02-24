const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));

// Root route for API check
app.get('/', (req, res) => {
  res.json({ status: 'ok', message: 'Server is running' });
});

// MongoDB connection
mongoose.connect('mongodb://localhost:27017/voice_assistant_db', {
  useNewUrlParser: true,
  useUnifiedTopology: true
})
.then(() => {
  console.log('✅ MongoDB Connected Successfully');
  mongoose.set('strictQuery', true);
})
.catch(err => console.error('❌ MongoDB connection error:', err));

// User Schema - only name and descriptor (no images)
const userSchema = new mongoose.Schema({
  name: { type: String, required: true, unique: true },
  faceDescriptor: { type: Array, required: true },
  lastLogin: { type: Date },
  loginCount: { type: Number, default: 0 },
  createdAt: { type: Date, default: Date.now }
});

const User = mongoose.model('User', userSchema);

// Similarity threshold
const SIMILARITY_THRESHOLD = 0.45;

// Calculate Euclidean distance
function calculateDistance(desc1, desc2) {
  if (!desc1 || !desc2 || desc1.length !== desc2.length) return Infinity;
  
  let sum = 0;
  for (let i = 0; i < desc1.length; i++) {
    const diff = desc1[i] - desc2[i];
    sum += diff * diff;
  }
  return Math.sqrt(sum);
}

// CHECK FACE endpoint - returns if face exists
app.post('/api/face/check', async (req, res) => {
  console.log('\n🔍 CHECKING FACE');
  
  try {
    const { descriptor } = req.body;
    
    if (!descriptor || descriptor.length !== 128) {
      return res.status(400).json({ success: false, error: 'Invalid descriptor' });
    }
    
    // Get all users
    const users = await User.find().lean();
    
    if (users.length === 0) {
      console.log('👤 No users in database');
      return res.json({ 
        success: false,
        exists: false,
        message: 'No existing users. Please register.',
        descriptor: descriptor
      });
    }
    
    // Compare with existing users
    let bestMatch = null;
    let bestDistance = Infinity;
    
    for (const user of users) {
      const distance = calculateDistance(descriptor, user.faceDescriptor);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestMatch = user;
      }
    }
    
    console.log(`Best match: ${bestMatch?.name || 'none'} (${bestDistance.toFixed(4)})`);
    
    if (bestMatch && bestDistance < SIMILARITY_THRESHOLD) {
      // Face exists
      return res.json({
        success: true,
        exists: true,
        name: bestMatch.name,
        matchDistance: bestDistance,
        descriptor: descriptor
      });
    } else {
      // New face
      return res.json({
        success: false,
        exists: false,
        message: 'New face - please register',
        descriptor: descriptor,
        closestMatch: bestMatch ? {
          name: bestMatch.name,
          distance: bestDistance
        } : null
      });
    }
    
  } catch (error) {
    console.error('❌ Check error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// VERIFY NAME endpoint - checks if name matches the face
app.post('/api/face/verify', async (req, res) => {
  console.log('\n🔍 VERIFYING NAME');
  
  try {
    const { name, descriptor } = req.body;
    
    if (!name || !descriptor) {
      return res.status(400).json({ success: false, error: 'Name and descriptor required' });
    }
    
    // Find user by name
    const user = await User.findOne({ name }).lean();
    
    if (!user) {
      // Name doesn't exist - treat as new user
      console.log(`👤 New name: ${name}`);
      return res.json({
        success: true,
        nameExists: false,
        message: 'New user - please complete registration'
      });
    }
    
    // Name exists - verify face matches
    const distance = calculateDistance(descriptor, user.faceDescriptor);
    console.log(`Face match distance for ${name}: ${distance.toFixed(4)}`);
    
    if (distance < SIMILARITY_THRESHOLD) {
      // Name AND face match - grant access
      console.log(`✅ Verified: ${name}`);
      
      // Update login stats
      await User.updateOne(
        { name },
        { lastLogin: new Date(), $inc: { loginCount: 1 } }
      );
      
      return res.json({
        success: true,
        verified: true,
        name: user.name,
        message: 'Access granted'
      });
      
    } else {
      // Name exists but face doesn't match
      console.log(`❌ Face mismatch for ${name}`);
      return res.json({
        success: false,
        verified: false,
        message: 'Face does not match this name',
        nameExists: true
      });
    }
    
  } catch (error) {
    console.error('❌ Verification error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// REGISTER new user
app.post('/api/face/register', async (req, res) => {
  console.log('\n📝 REGISTERING NEW USER');
  
  try {
    const { name, descriptor } = req.body;
    
    // Check if name already exists
    const existingUser = await User.findOne({ name });
    if (existingUser) {
      return res.status(400).json({ 
        success: false, 
        error: 'Name already exists. Please choose a different name.' 
      });
    }
    
    // Check if face already exists (prevent duplicate faces with different names)
    const allUsers = await User.find().lean();
    for (const user of allUsers) {
      const distance = calculateDistance(descriptor, user.faceDescriptor);
      if (distance < SIMILARITY_THRESHOLD) {
        return res.status(400).json({
          success: false,
          error: `This face appears to be already registered as ${user.name}. Please use that name.`
        });
      }
    }
    
    // Save new user
    const user = new User({ 
      name, 
      faceDescriptor: descriptor,
      loginCount: 1
    });
    await user.save();
    
    console.log(`✅ New user registered: ${name}`);
    
    res.json({ 
      success: true, 
      message: 'Registration successful',
      name: user.name
    });
    
  } catch (error) {
    console.error('❌ Registration error:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get all users (for debugging)
app.get('/api/users', async (req, res) => {
  try {
    const users = await User.find().select('-faceDescriptor').lean();
    res.json({ success: true, count: users.length, users });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Delete user (for testing)
app.delete('/api/user/:name', async (req, res) => {
  try {
    await User.deleteOne({ name: req.params.name });
    console.log(`🗑️ Deleted user: ${req.params.name}`);
    res.json({ success: true, message: 'User deleted' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

const PORT = 5000;
app.listen(PORT, () => {
  console.log('\n🚀 FACE RECOGNITION SERVER (No Images)');
  console.log(`📡 Port: ${PORT}`);
  console.log(`🎯 Similarity threshold: ${SIMILARITY_THRESHOLD}`);
  console.log('✅ Ready to accept requests\n');
});