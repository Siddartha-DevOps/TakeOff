"import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Calendar, User, Clock, ArrowRight, Sparkles } from 'lucide-react';
import axios from 'axios';

export default function Blog() {
  const [blogs, setBlogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBlogs();
  }, []);

  const fetchBlogs = async () => {
    try {
      const API_URL = process.env.REACT_APP_BACKEND_URL || 'https://mock-takeoff.preview.emergentagent.com';
      const response = await axios.get(`${API_URL}/api/blogs`);
      setBlogs(response.data);
    } catch (error) {
      console.error('Failed to fetch blogs:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className=\"min-h-screen flex items-center justify-center\">
        <div className=\"text-slate-600\">Loading insights...</div>
      </div>
    );
  }

  return (
    <div className=\"min-h-screen bg-white\">
      {/* Hero Section */}
      <section className=\"relative overflow-hidden gradient-soft-bg py-20\">
        <div className=\"absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]\" />
        
        <div className=\"relative max-w-6xl mx-auto px-6\">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className=\"text-center\"
          >
            <div className=\"inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm mb-6\">
              <Sparkles className=\"w-3 h-3 text-indigo-500\" /> Insights Hub
            </div>
            <h1 className=\"text-5xl md:text-6xl font-semibold tracking-tight text-slate-900\">
              TakeOff.ai Insights
            </h1>
            <p className=\"mt-4 text-lg text-slate-600 max-w-2xl mx-auto\">
              Expert perspectives on AI-powered construction takeoffs, industry trends, and best practices.
            </p>
          </motion.div>
        </div>
      </section>

      {/* Blog Grid */}
      <section className=\"max-w-6xl mx-auto px-6 py-16\">
        <div className=\"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8\">
          {blogs.map((blog, index) => (
            <motion.article
              key={blog.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: index * 0.1 }}
              className=\"group rounded-2xl border border-slate-200 bg-white overflow-hidden hover:border-slate-300 hover:shadow-lg transition-all\"
            >
              <Link to={`/blog/${blog.id}`} className=\"block\">
                {/* Tags */}
                <div className=\"p-6 pb-4\">
                  <div className=\"flex flex-wrap gap-2 mb-3\">
                    {blog.tags.slice(0, 2).map((tag) => (
                      <span
                        key={tag}
                        className=\"px-2 py-0.5 text-xs font-medium rounded-full bg-indigo-50 text-indigo-700\"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>

                  {/* Title */}
                  <h2 className=\"text-lg font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors leading-tight mb-2\">
                    {blog.title}
                  </h2>

                  {/* Excerpt */}
                  <p className=\"text-sm text-slate-600 line-clamp-3 mb-4\">
                    {blog.excerpt}
                  </p>

                  {/* Meta */}
                  <div className=\"space-y-2 text-xs text-slate-500\">
                    <div className=\"flex items-center gap-2\">
                      <User className=\"w-3.5 h-3.5\" />
                      <span className=\"font-medium text-slate-700\">{blog.author_name}</span>
                      <span>·</span>
                      <span>{blog.author_role}</span>
                    </div>
                    <div className=\"flex items-center gap-2\">
                      <span className=\"text-slate-400\">{blog.author_company}</span>
                    </div>
                    <div className=\"flex items-center gap-4 pt-2 border-t border-slate-100\">
                      <div className=\"flex items-center gap-1.5\">
                        <Calendar className=\"w-3.5 h-3.5\" />
                        {new Date(blog.created_at).toLocaleDateString('en-US', {
                          month: 'short',
                          day: 'numeric',
                          year: 'numeric',
                        })}
                      </div>
                      <div className=\"flex items-center gap-1.5\">
                        <Clock className=\"w-3.5 h-3.5\" />
                        {blog.read_time}
                      </div>
                    </div>
                  </div>

                  {/* Read More */}
                  <div className=\"mt-4 flex items-center gap-1 text-sm font-medium text-indigo-600 group-hover:gap-2 transition-all\">
                    Read article <ArrowRight className=\"w-3.5 h-3.5\" />
                  </div>
                </div>
              </Link>
            </motion.article>
          ))}
        </div>
      </section>

      {/* CTA Section */}
      <section className=\"max-w-4xl mx-auto px-6 py-16\">
        <div className=\"rounded-2xl bg-gradient-to-br from-slate-900 to-indigo-900 p-12 text-center text-white\">
          <h2 className=\"text-3xl font-semibold mb-4\">
            Ready to transform your takeoff process?
          </h2>
          <p className=\"text-slate-300 mb-8 max-w-2xl mx-auto\">
            Join thousands of estimators using AI-powered tools to save time and improve accuracy.
          </p>
          <div className=\"flex gap-3 justify-center\">
            <Link
              to=\"/demo\"
              className=\"px-6 py-3 rounded-lg bg-white text-slate-900 font-medium hover:bg-slate-100 transition-colors\"
            >
              Book a Demo
            </Link>
            <Link
              to=\"/pricing\"
              className=\"px-6 py-3 rounded-lg bg-white/10 border border-white/20 text-white font-medium hover:bg-white/20 transition-colors\"
            >
              View Pricing
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
"